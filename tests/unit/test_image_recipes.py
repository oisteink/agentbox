"""Recipe inputs and automatic preparation, without executing Docker on the host."""

import io
import os
import shlex
import sys

import pytest

from agentbox import cli, images
from agentbox.config import parse
from agentbox.errors import AgentboxError
from agentbox.output import Output, failure, success


@pytest.fixture
def recipes(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    return tmp_path / "agentbox/images"


def test_default_and_local_template_priority_are_independent(recipes):
    images.new("default", "base")
    source = recipes / "default"
    (source / "Dockerfile").write_text("FROM custom-default\n")
    (source / ".dockerignore").write_text("private\n")
    (source / "nested").mkdir()
    script = source / "nested/helper"
    script.write_text("#!/bin/sh\nexit 0\n")
    script.chmod(0o755)
    (source / "link").symlink_to("nested/helper")
    images.new("copy")
    copy = recipes / "copy"
    assert (copy / "Dockerfile").read_text() == "FROM custom-default\n"
    assert (copy / ".dockerignore").read_text() == "private\n"
    assert (copy / "nested/helper").stat().st_mode & 0o111
    assert (copy / "link").is_symlink()
    script.write_text("changed")
    assert (copy / "nested/helper").read_text() != "changed"
    images.new("codex", "base")
    (recipes / "codex/Dockerfile").write_text("FROM local-codex\n")
    images.new("override", "codex")
    assert (recipes / "override/Dockerfile").read_text() == "FROM local-codex\n"
    with pytest.raises(AgentboxError, match="already exists"):
        images.new("copy")


def test_invalid_local_default_is_not_silently_replaced(recipes):
    recipes.mkdir(parents=True)
    (recipes / "default").symlink_to(recipes / "missing")
    with pytest.raises(AgentboxError, match="Dockerfile missing"):
        images.new("copy")
    assert not (recipes / "copy").exists()


def test_fingerprint_tracks_input_not_timestamps_and_matches_archive(recipes):
    images.new("example")
    path = recipes / "example"
    data = path / "helper"
    data.write_bytes(b"bytes\\x00\\xff")
    first = images.fingerprint("example")
    os.utime(data, (1, 1))
    assert images.fingerprint("example") == first
    data.chmod(0o755)
    assert images.fingerprint("example") != first
    executable = images.fingerprint("example")
    data.write_bytes(b"different")
    assert images.fingerprint("example") != executable
    archive = io.BytesIO()
    images.archive("example", archive)
    archive.seek(0)
    assert images.fingerprint_archive(archive) == images.fingerprint("example")
    (path / ".env").write_text("ignored input is still part of transferred context")
    assert images.fingerprint("example") != images.fingerprint_archive(archive)


def test_edit_reports_nested_context_changes_even_with_nonzero_editor_exit(
    recipes, tmp_path, monkeypatch
):
    images.new("example")
    script = tmp_path / "editor.py"
    script.write_text(
        "from pathlib import Path; Path('helper').write_text('new'); raise SystemExit(19)"
    )
    monkeypatch.setenv("VISUAL", shlex.join([sys.executable, str(script)]))
    result = images.edit("example")
    assert result["changed"] and result["exit_code"] == 19
    result = images.edit("example")
    assert not result["changed"] and result["exit_code"] == 19


def env():
    return parse(
        {
            "name": "example",
            "image": "recipe",
            "mounts": [{"source": "data", "target": "/workspace"}],
        }
    )


def test_pending_snapshot_then_stopped_rebuilds_in_same_action(monkeypatch):
    digest = "1" * 64
    statuses = iter([{"example": {"containers": {"agent": "running"}}}, {}])
    builds = []
    starts = []

    def rpc(request, **kwargs):
        if request["action"] == "status":
            return next(statuses)
        if request["action"] == "image" and request["operation"] == "inspect":
            return {"status": "stale", "digest": "0" * 64}
        if request["action"] == "image":
            builds.append(kwargs["context"])
            return {"digest": digest}
        starts.append(request)
        if len(starts) == 1:
            raise AgentboxError("Stopped after pending snapshot", code="image_outdated")
        return {"resources": {"agent": "new"}}

    monkeypatch.setattr(images, "fingerprint", lambda name: digest)
    monkeypatch.setattr(cli, "rpc", rpc)
    monkeypatch.setattr(cli, "_output", Output(False))
    assert cli.prepared_environment(env())["resources"]["agent"] == "new"
    assert builds == ["recipe"] and len(starts) == 2
    assert all(request["recipe_digest"] == digest for request in starts)


@pytest.mark.parametrize(
    "ready,interrupted,retries", [(False, False, 2), (True, False, 1), (False, True, 1)]
)
def test_run_retries_only_before_ready_and_without_interrupt(
    monkeypatch, ready, interrupted, retries
):
    calls = []
    monkeypatch.setattr(cli, "ensure_image", lambda environment, **kwargs: "1" * 64)

    def rpc(request, **kwargs):
        calls.append(request)
        if len(calls) == 1:
            return cli.StreamResult(
                failure("image_outdated", "Changed"), input_ready=ready, interrupted=interrupted
            )
        return cli.StreamResult(success(exit_code=0), input_ready=True)

    monkeypatch.setattr(cli, "rpc", rpc)
    cli.run_environment(env())
    assert len(calls) == retries
