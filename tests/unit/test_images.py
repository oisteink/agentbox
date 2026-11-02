import io
import json
import os
import tarfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentbox import cli, images
from agentbox.config import parse
from agentbox.errors import AgentboxError


@pytest.fixture
def recipes(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "agentbox/images"


def test_new_recipe_preserves_user_changes_and_lists_unbuilt(recipes):
    images.new("js")
    path = recipes / "js"
    assert (path / ".dockerignore").is_file()
    (path / "Dockerfile").write_text("FROM node:22-bookworm-slim\n")
    with pytest.raises(AgentboxError, match="already exists"):
        images.new("js")
    assert (path / "Dockerfile").read_text() == "FROM node:22-bookworm-slim\n"
    assert images.names() == ["js"]
    images.new("codex", "codex")
    assert "@openai/codex" in (recipes / "codex/Dockerfile").read_text()
    assert "--no-daemon" in (recipes / "codex/codex").read_text()


def test_tar_preserves_binary_modes_and_links_without_external_content(recipes, tmp_path):
    images.new("js")
    path = recipes / "js"
    (path / "bytes").write_bytes(b"\x00\xff\xfe\x80")
    (path / "bytes").chmod(0o755)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "private").write_text("outside context")
    (path / "external").symlink_to(outside, target_is_directory=True)
    context = io.BytesIO()
    images.archive("js", context)
    context.seek(0)
    with tarfile.open(fileobj=context) as archive:
        assert archive.extractfile("./bytes").read() == b"\x00\xff\xfe\x80"
        assert archive.getmember("./bytes").mode & 0o111
        assert archive.getmember("./external").issym()
        assert not any(member.name.endswith("private") for member in archive)


def test_special_files_fail_before_context_is_sent(recipes):
    images.new("js")
    os.mkfifo(recipes / "js/fifo")
    with pytest.raises(AgentboxError, match="Special file"):
        images.archive("js", io.BytesIO())


@pytest.mark.parametrize("name", ["../escape", "--flag", "node:22", "registry.example/js", "JS"])
def test_only_local_names_are_accepted(recipes, name):
    with pytest.raises(AgentboxError):
        images.new(name)
    with pytest.raises(AgentboxError):
        parse({"name": "example", "image": name, "mounts": []})
    assert not recipes.exists()


def test_rpc_transfers_json_header_and_complete_binary_tar(recipes, monkeypatch):
    images.new("js")
    (recipes / "js/binary").write_bytes(b"\xff\x00\x80")
    seen = []

    def run(command, *, stdin, **kwargs):
        assert command[-1] == "/usr/local/libexec/agentbox-control"
        seen.append(json.loads(stdin.readline()))
        with tarfile.open(fileobj=stdin) as archive:
            assert archive.extractfile("./binary").read() == b"\xff\x00\x80"
        return SimpleNamespace(returncode=0, stdout='{"status":"built"}')

    monkeypatch.setattr(cli.subprocess, "run", run)
    request = {"action": "image", "operation": "build", "name": "js"}
    assert cli.rpc(request, context="js") == {"status": "built"}
    assert seen == [request]


def test_control_reads_binary_context_after_authentication(monkeypatch, capsys):
    uid = os.getuid()
    monkeypatch.setattr(cli, "load_settings", lambda: {"service_uid": uid, "operator_uid": uid})
    monkeypatch.setenv("SUDO_UID", str(uid))
    header = json.dumps({"action": "image", "operation": "build", "name": "js"}).encode()
    payload = b"\x00\xff\xfe\x80" * 300000  # Context is not limited by JSON's 1 MiB limit.
    source = io.TextIOWrapper(io.BytesIO(header + b"\n" + payload))
    monkeypatch.setattr("sys.stdin", source)

    def dispatch(self, request, context=None):
        assert request["name"] == "js"
        assert context.read() == payload
        return {"status": "built"}

    monkeypatch.setattr(cli.Control, "__init__", lambda self, settings: None)
    monkeypatch.setattr(cli.Control, "dispatch", dispatch)
    cli.control_main()
    assert json.loads(capsys.readouterr().out) == {"status": "built"}


class ImageDocker:
    """Only the daemon boundary; container IDs refer to actual inspect response fields."""

    def __init__(self, used=False):
        self.image = {
            "Id": "sha256:built",
            "Architecture": "amd64",
            "Config": {"Labels": {"agentbox.installation": "test", "agentbox.image": "js"}},
        }
        self.used = used
        self.mutations = []

    def run(self, *args):
        if args[:2] == ("image", "ls"):
            return SimpleNamespace(stdout=self.image["Id"] if self.image else "")
        assert args == ("container", "ls", "-aq", "--no-trunc")
        return SimpleNamespace(stdout="container descendant")

    def inspect(self, kind, identifier):
        if kind == "image":
            return self.image
        return {
            "Image": "sha256:built"
            if identifier == "container" and self.used
            else "sha256:derived",
            "Name": "/" + identifier,
            "State": {"Running": False},
        }

    def mutate(self, *args, **kwargs):
        if args[0] == "build":
            assert (Path(args[-1]) / "Dockerfile").is_file()
        self.mutations.append(args)


def build_context():
    source = io.BytesIO()
    with tarfile.open(fileobj=source, mode="w") as bundle:
        data = b"FROM ubuntu:24.04\n"
        member = tarfile.TarInfo("Dockerfile")
        member.size = len(data)
        bundle.addfile(member, io.BytesIO(data))
    source.seek(0)
    return source


def test_build_rejects_stopped_container_before_mutation():
    docker = ImageDocker(used=True)
    with pytest.raises(AgentboxError, match="including stopped.*container"):
        images.build(docker, "test", "js", io.BytesIO(b"tar"))
    assert docker.mutations == []


def test_derived_image_does_not_block_build():
    docker = ImageDocker()
    assert images.build(docker, "test", "js", build_context())["status"] == "built"
    assert docker.mutations[0][:3] == ("build", "--tag", "agentbox-image-js:local")
    assert not Path(docker.mutations[0][-1]).exists()


def test_foreign_tag_is_not_an_agentbox_build():
    docker = ImageDocker()
    docker.image["Config"]["Labels"]["agentbox.installation"] = "other"
    with pytest.raises(AgentboxError, match="not owned"):
        images.build(docker, "test", "js", build_context())
    assert docker.mutations == []


def test_invalid_built_profile_is_reported_as_failure():
    docker = ImageDocker()
    docker.image["Config"]["Volumes"] = {"/data": {}}
    with pytest.raises(AgentboxError, match="VOLUME"):
        images.build(docker, "test", "js", build_context())


@pytest.mark.parametrize("kind", ["path", "link", "device"])
def test_unsafe_archive_fails_without_mutation_or_external_files(tmp_path, kind):
    docker = ImageDocker()
    outside = tmp_path / "outside"
    source = io.BytesIO()
    with tarfile.open(fileobj=source, mode="w") as bundle:
        member = tarfile.TarInfo(str(outside) if kind == "path" else "unsafe")
        if kind == "path":
            member.name = "../../" + str(outside).lstrip("/")
        elif kind == "link":
            member.type = tarfile.SYMTYPE
            member.linkname = str(outside)
        else:
            member.type = tarfile.CHRTYPE
        bundle.addfile(member)
    source.seek(0)
    with pytest.raises(AgentboxError, match="unsafe build context"):
        images.build(docker, "test", "js", source)
    assert not outside.exists()
    assert docker.mutations == []


def test_missing_build_has_actionable_error():
    docker = ImageDocker()
    docker.image = None
    with pytest.raises(AgentboxError, match="abx image build js"):
        images.managed(docker, "test", "js")


@pytest.mark.parametrize("action", ["rm", "proxy-build"])
def test_control_removal_and_proxy_build_share_use_guard(tmp_path, monkeypatch, action):
    from agentbox.control import Control

    control = Control({"home": str(tmp_path), "service_uid": os.getuid(), "proxy_image": "proxy"})
    control.docker = ImageDocker(used=True)
    monkeypatch.setattr(control, "verified", lambda data: data.update(installation="test"))
    request = (
        {"action": "image", "operation": "rm", "name": "js"}
        if action == "rm"
        else {"action": "proxy", "operation": "build"}
    )
    with pytest.raises(AgentboxError, match="Image is in use"):
        control.dispatch(request)
    assert control.docker.mutations == []


def test_completion_only_reads_local_recipes(recipes, monkeypatch):
    from agentbox import completion

    images.new("js")
    monkeypatch.setattr(
        completion.subprocess, "run", lambda *args, **kwargs: pytest.fail("No sudo lookup")
    )
    assert completion.names("images") == ["js"]
