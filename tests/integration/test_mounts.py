"""Directory ACL cleanup and durable named volumes through the installed CLI."""

import json
import pwd
import subprocess

import pytest
import yaml
from conftest import cli, machine


def test_volume_profiles_survive_remove_run_and_image_change(lab):
    directory, _ = lab.mount()
    profile = lab.volume()
    name, path = lab.configuration(
        directory,
        mounts=[
            {"source": directory, "target": "/workspace"},
            {"source": profile, "target": "/home/agent/.config/tool"},
            {"source": profile, "target": "/readonly-profile", "mode": "ro"},
        ],
    )
    cli("start", "--keep-running", str(path))
    cli("exec", name, "--", "sh", "-c", "printf retained > /home/agent/.config/tool/config")
    assert cli("exec", name, "--", "cat", "/readonly-profile/config").stdout == "retained"
    assert (
        cli(
            "exec", name, "--", "sh", "-c", "echo forbidden > /readonly-profile/config", check=False
        ).returncode
        != 0
    )
    entry = json.loads(cli("mount", "list").stdout)[profile]
    assert entry["type"] == "volume"
    cli("stop", name)
    assert json.loads(cli("mount", "list").stdout)[profile]["status"] == "active"
    cli("remove", name)
    lab.assert_removed(name)
    data = yaml.safe_load(path.read_text())
    data["command"] = ["cat", "/home/agent/.config/tool/config"]
    path.write_text(yaml.safe_dump(data))
    assert cli("run", str(path)).stdout == "retained"
    lab.assert_removed(name)
    data["image"] = "codex"
    path.write_text(yaml.safe_dump(data))
    cli("start", "--keep-running", str(path))
    assert cli("exec", name, "--", "cat", "/home/agent/.config/tool/config").stdout == "retained"
    cli("remove", name)
    removed = machine("mount", "remove", profile)[-1]
    assert (
        removed["ok"]
        and removed["data"]["type"] == "volume"
        and removed["data"]["data"] == "deleted"
    )
    assert lab.docker("volume", "inspect", entry["volume"], check=False).returncode != 0


def test_nonpersistent_home_uses_explicit_volume(lab):
    home = lab.volume("home")
    name, path = lab.configuration(
        home,
        persistent=False,
        mounts=[{"source": home, "target": "/home/agent"}],
        command=["sh", "-c", 'test "$HOME" = /home/agent; echo retained > "$HOME/marker"'],
    )
    cli("start", "--keep-running", str(path))
    first = lab.state(name)["resources"]["agent"]
    cli("stop", name)
    lab.assert_removed(name)
    cli("start", "--keep-running", str(path))
    assert lab.state(name)["resources"]["agent"] != first
    assert cli("exec", name, "--", "cat", "/home/agent/marker").stdout == "retained\n"
    cli("stop", name)
    lab.assert_removed(name)
    assert json.loads(cli("mount", "check", home).stdout)["issues"] == []


def test_volume_revoke_reactivate_and_remove_stopped_users(lab):
    source = lab.volume()
    first = lab.start(source)
    second = lab.start(source)
    cli("exec", first, "--", "sh", "-c", "printf retained > /workspace/data")
    revoked = cli("mount", "revoke", source)
    assert (
        first in revoked.stderr
        and second in revoked.stderr
        and "open file handles" in revoked.stderr
    )
    assert cli("exec", second, "--", "cat", "/workspace/data").stdout == "retained"
    assert json.loads(cli("mount", "check", source, "--fix").stdout)["status"] == "revoked"
    third, path = lab.configuration(source)
    rejected = machine("start", str(path))[-1]
    assert rejected["error"]["code"] == "mount_unavailable"
    lab.assert_removed(third)
    cli("mount", "add", source, "--volume")
    assert cli("exec", first, "--", "cat", "/workspace/data").stdout == "retained"
    cli("stop", first)
    refused = machine("mount", "remove", source)[-1]
    assert refused["error"]["code"] == "confirmation_required"
    assert refused["error"]["details"]["affected"] == sorted([first, second])
    assert json.loads(cli("mount", "list").stdout)[source]["status"] == "active"
    assert cli("exec", second, "--", "cat", "/workspace/data").stdout == "retained"
    cli("mount", "remove", source, "--yes")
    lab.assert_removed(first)
    lab.assert_removed(second)
    assert source not in json.loads(cli("mount", "list").stdout)


@pytest.mark.parametrize("persistent", [True, False])
def test_directory_remove_requires_consent_and_keeps_data_access(lab, persistent):
    source, root = lab.mount()
    name = lab.start(source, persistent=persistent)
    cli("exec", name, "--", "sh", "-c", "printf retained > /workspace/data")
    other = lab.root / "other"
    other.mkdir()
    protected = other / "protected"
    protected.write_text("unrelated")
    (root / "external-link").symlink_to(other, target_is_directory=True)
    protected_acl = subprocess.check_output(["getfacl", "-cpn", str(protected)], text=True)
    assert machine("mount", "add", source, str(other))[-1]["error"]["code"] == "mount_conflict"
    assert machine("mount", "add", source, "--volume")[-1]["error"]["code"] == "mount_conflict"
    refused = machine("mount", "remove", source)[-1]
    assert refused["error"]["code"] == "confirmation_required"
    assert refused["error"]["details"]["approval"]["environments"][name]["operation"] == (
        "stop" if persistent else "remove"
    )
    assert lab.state(name)["status"] == "running"
    removed = machine("mount", "remove", source, "--yes")[-1]["data"]
    assert removed["data"] == "retained" and "unchanged" in removed["ownership"]
    assert "uninstall" in removed["note"]
    if persistent:
        assert lab.state(name)["status"] == "stopped"
    else:
        lab.assert_removed(name)
    assert (root / "data").read_text() == "retained"
    assert subprocess.check_output(["getfacl", "-cpn", str(protected)], text=True) == protected_acl
    assert (root / "data").stat().st_uid == pwd.getpwnam("agentbox").pw_uid
    acl = subprocess.check_output(["getfacl", "-cpn", str(root)], text=True)
    assert f"user:{pwd.getpwnam('agentbox').pw_uid}:" not in acl
    assert machine("start", str(lab.environments[name]))[-1]["error"]["code"] == "mount_unavailable"
    # Re-registration is explicit; durable operator access survives cleanup.
    cli("mount", "add", source, str(root))
    assert (root / "data").read_text() == "retained"


def test_directory_revoke_keeps_open_handle_and_fix_does_not_reactivate(lab):
    source, root = lab.mount()
    (root / "data").write_text("retained")
    name = lab.start(source)
    program = "import sys; f=open('/workspace/data'); print('ready',flush=True); sys.stdin.readline(); print(f.read(),flush=True)"
    with subprocess.Popen(
        ["abx", "exec", name, "--", "python3", "-c", program],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        assert process.stdout.readline() == "ready\n"
        revoked = cli("mount", "revoke", source)
        assert name in revoked.stderr
        checked = machine("mount", "check", source, "--fix")[-1]
        assert checked["ok"] and checked["data"]["status"] == "revoked"
        process.stdin.write("release\n")
        process.stdin.flush()
        process.stdin.close()
        assert process.stdout.read() == "retained\n"
        assert process.wait(timeout=15) == 0
    cli("stop", name)
    assert machine("start", str(lab.environments[name]))[-1]["error"]["code"] == "mount_unavailable"
    cli("mount", "add", source, str(root))
    cli("start", "--keep-running", str(lab.environments[name]))
    assert cli("exec", name, "--", "cat", "/workspace/data").stdout == "retained"
    cli("mount", "revoke", source)
    cli("remove", name)
    assert machine("mount", "remove", source)[-1]["ok"]
    assert (root / "data").read_text() == "retained"


def test_directory_cleanup_failure_keeps_registration_for_retry(lab):
    source, root = lab.mount()
    (root / "data").write_text("retained")
    blocker = root / "unsupported"
    import os

    os.mkfifo(blocker)
    failed = machine("mount", "remove", source)[-1]
    assert not failed["ok"]
    assert json.loads(cli("mount", "list").stdout)[source]["status"] == "removing"
    assert machine("mount", "check", source, "--fix")[-1]["error"]["code"] == "mount_removing"
    assert machine("mount", "add", source, str(root))[-1]["error"]["code"] == "mount_removing"
    blocker.unlink()
    assert machine("mount", "remove", source)[-1]["ok"]
    assert source not in json.loads(cli("mount", "list").stdout)
    assert (root / "data").read_text() == "retained"


def test_missing_or_foreign_volume_is_not_recreated_or_deleted(lab):
    source = lab.volume()
    entry = json.loads(cli("mount", "list").stdout)[source]
    lab.docker("volume", "rm", entry["volume"])
    failed = machine("mount", "check", source, "--fix")[-1]
    assert not failed["ok"] and not failed["error"]["details"]["changed"]
    assert lab.docker("volume", "inspect", entry["volume"], check=False).returncode != 0
    lab.docker("volume", "create", entry["volume"])
    try:
        assert not machine("mount", "check", source)[-1]["ok"]
        failed_remove = machine("mount", "remove", source)[-1]
        assert failed_remove["error"]["code"] == "mount_identity_changed"
        assert lab.docker("volume", "inspect", entry["volume"]).returncode == 0
        assert source in json.loads(cli("mount", "list").stdout)
    finally:
        lab.docker("volume", "rm", entry["volume"])
    # Explicit remove can forget the missing source; diagnosis never does this.
    assert machine("mount", "remove", source)[-1]["ok"]
