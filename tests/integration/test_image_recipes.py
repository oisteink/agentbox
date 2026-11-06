"""Template resolution and automatic image preparation in installed rootless Docker."""

import json
from pathlib import Path

from conftest import cli, machine


def test_installed_local_default_and_template_copy(lab):
    root = Path.home() / ".config/agentbox/images"
    for name in ("base", "default", "default-copy", "base-copy"):
        assert not (root / name).exists()
        lab.images[name] = root / name
    cli("image", "new", "base", "--template", "base")
    base = root / "base"
    (base / "Dockerfile").write_text("FROM agentbox-image-smoke:local\n# local base\n")
    (base / "nested").mkdir()
    (base / "nested/helper").write_text("#!/bin/sh\nexit 0\n")
    (base / "nested/helper").chmod(0o755)
    (base / "link").symlink_to("nested/helper")
    (base / ".dockerignore").write_text("private\n")
    cli("image", "new", "default", "--template", "base")
    default = root / "default"
    (default / "Dockerfile").write_text("FROM agentbox-image-smoke:local\n# local default\n")
    cli("image", "new", "default-copy")
    cli("image", "new", "base-copy", "--template", "base")
    assert "local default" in (root / "default-copy/Dockerfile").read_text()
    assert "local base" in (root / "base-copy/Dockerfile").read_text()
    assert (root / "default-copy/.dockerignore").read_text() == "private\n"
    assert (root / "default-copy/link").is_symlink()
    assert (root / "default-copy/nested/helper").stat().st_mode & 0o111
    (default / "nested/helper").write_text("changed")
    assert (root / "default-copy/nested/helper").read_text() != "changed"
    assert cli("image", "new", "default-copy", check=False).returncode != 0
    completed = cli("completion", "--names", "templates").stdout.splitlines()
    assert {"base", "codex", "opencode", "claude-code", "default", "default-copy"}.issubset(
        completed
    )


def test_exec_builds_and_starts_from_configuration(lab):
    recipe, path = lab.image()
    (path / "Dockerfile").write_text("FROM agentbox-image-smoke:local\nCOPY marker /marker\n")
    (path / "marker").write_text("first")
    source, root = lab.mount()
    (root / "data").write_text("retained")
    name, _ = lab.configuration(source, image=recipe)
    assert cli("exec", name, "--", "cat", "/marker").stdout == "first"
    original = lab.state(name)["resources"]["agent"]
    assert json.loads(cli("image", "inspect", recipe).stdout)["status"] == "built"
    cli("stop", name)
    (path / "marker").write_text("second")
    assert cli("exec", name, "--", "cat", "/marker").stdout == "second"
    assert lab.state(name)["resources"]["agent"] != original
    assert (root / "data").read_text() == "retained"


def test_running_use_guard_survives_tag_move(lab):
    recipe, path = lab.image()
    (path / "Dockerfile").write_text("FROM agentbox-image-smoke:local\n")
    source, _ = lab.mount()
    name = lab.start(source, image=recipe)
    agent = lab.state(name)["resources"]["agent"]
    original = json.loads(cli("image", "inspect", recipe).stdout)["id"]
    tag = "agentbox-image-" + recipe + ":local"
    moved = lab.docker("commit", agent, tag).stdout.strip()
    assert moved != original
    blocked = machine("image", "build", recipe)[-1]
    assert blocked["error"]["code"] == "image_in_use"
    assert name in json.loads(cli("image", "inspect", recipe).stdout)["environments"]
    cli("stop", name)
    cli("image", "build", recipe)
    assert machine("image", "remove", recipe)[-1]["error"]["code"] == "image_in_use"


def test_exec_does_not_reopen_stopped_proxy_and_pending_keeps_it_missing(lab):
    recipe, path = lab.image()
    (path / "Dockerfile").write_text("FROM agentbox-image-smoke:local\nCOPY marker /marker\n")
    (path / "marker").write_text("first")
    source, _ = lab.mount()
    name = lab.start(source, image=recipe)
    agent = lab.state(name)["resources"]["agent"]
    cli("proxy", "stop", name)
    cli("start", str(lab.environments[name]))
    assert "proxy" not in lab.state(name)["resources"]
    assert cli("exec", name, "--", "echo", "offline").stdout == "offline\n"
    assert "proxy" not in lab.state(name)["resources"]
    (path / "marker").write_text("pending")
    pending = cli("start", "--keep-running", str(lab.environments[name]))
    assert "next startup" in pending.stderr
    assert lab.state(name)["resources"]["agent"] == agent
    assert "proxy" not in lab.state(name)["resources"]
    assert cli("exec", name, "--", "cat", "/marker").stdout == "first"
    assert "proxy" not in lab.state(name)["resources"]


def test_invalid_new_mount_keeps_stopped_layer(lab):
    import yaml

    source, _ = lab.mount()
    name = lab.start(source)
    agent = lab.state(name)["resources"]["agent"]
    cli("exec", name, "--", "sh", "-c", "echo retained > /home/agent/marker")
    cli("stop", name)
    path = lab.environments[name]
    original = path.read_text()
    data = yaml.safe_load(original)
    data["mounts"][0]["source"] = "unregistered"
    path.write_text(yaml.safe_dump(data))
    assert not machine("start", str(path))[-1]["ok"]
    assert lab.state(name)["resources"]["agent"] == agent
    path.write_text(original)
    cli("start", "--keep-running", str(path))
    assert cli("exec", name, "--", "cat", "/home/agent/marker").stdout == "retained\n"


def test_run_builds_before_forwarding_large_input(lab):
    recipe, path = lab.image()
    (path / "Dockerfile").write_text("FROM agentbox-image-smoke:local\n")
    source, _ = lab.mount()
    name, config = lab.configuration(
        source,
        image=recipe,
        command=[
            "python3",
            "-c",
            "import sys; data=sys.stdin.read(); print(len(data)); assert data == 'x'*300000",
        ],
    )
    frames = machine("run", str(config), input="x" * 300000)
    assert frames[-1]["ok"] and frames[-1]["exit_code"] == 0
    output = "".join(
        frame["data"]
        for frame in frames[:-1]
        if frame["type"] == "output" and frame["stream"] == "stdout"
    )
    assert output == "300000\n"
    lab.assert_removed(name)
