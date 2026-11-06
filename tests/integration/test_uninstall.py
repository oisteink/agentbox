"""Destructive uninstall acceptance test: explicitly opt in inside the disposable VM."""

import json
import os
import pwd
import shutil
import socket
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTBOX_UNINSTALL_LAB") != "1" or socket.gethostname() != "agentbox-lab",
    reason="destroys the disposable lab installation; requires explicit opt-in",
)


def run(*args, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True, timeout=180)


def test_full_uninstall_keeps_mounts_and_returns_ownership():
    service_uid = pwd.getpwnam("agentbox").pw_uid
    operator_uid = os.getuid()
    token = uuid.uuid4().hex[:8]
    rootful_id = run(
        "sudo", "docker", "--host", "unix:///var/run/docker.sock", "info", "--format", "{{.ID}}"
    ).stdout.strip()
    active_name, revoked_name = "active-" + token, "revoked-" + token
    env = "uninstall-" + token
    parent = Path(tempfile.mkdtemp(prefix="agentbox-uninstall-", dir=Path.home()))
    active, revoked, outside = (parent / name for name in ("active", "revoked", "outside"))
    for path in (active, revoked, outside):
        path.mkdir()
    outside.chmod(0o700)  # Skipping a nested mount must not require access to its root.
    mount = active / "nested"
    registered = []
    volume_source = "uninstall-" + token
    volume_name = "agentbox-mount-" + volume_source
    rootful_volume = run(
        "sudo", "docker", "--host", "unix:///var/run/docker.sock", "volume", "create", volume_name
    ).stdout.strip()
    rootful_before = run(
        "sudo",
        "docker",
        "--host",
        "unix:///var/run/docker.sock",
        "volume",
        "inspect",
        rootful_volume,
    ).stdout
    try:
        run("abx", "mount", "add", volume_source, "--volume")
        protected = outside / "protected"
        protected.write_text("outside content")
        run("sudo", "chown", "root:root", str(protected))
        protected_identity = protected.stat()
        (active / "developer-file").write_text("keep developer code")
        for name, path in ((active_name, active), (revoked_name, revoked)):
            registered.append(name)
            run("abx", "mount", "add", name, str(path))
        # Simulate a file from an earlier, now revoked environment.
        run(
            "sudo",
            "-u",
            "agentbox",
            "sh",
            "-c",
            'printf retained > "$1"; chmod 600 "$1"',
            "sh",
            str(revoked / "retained"),
        )
        run("abx", "mount", "revoke", revoked_name)
        # Manual ancestor ACL edits must survive uninstall.
        run("setfacl", "-m", "u:65534:--x", str(parent))
        before_parent_acl = run("getfacl", "-cpn", str(parent)).stdout
        mount.mkdir()
        run("sudo", "mount", "--bind", str(outside), str(mount))
        cfg = parent / "environment.yaml"
        cfg.write_text(
            yaml.safe_dump(
                {
                    "name": env,
                    "image": "smoke",
                    "command": ["bash"],
                    "mounts": [
                        {"source": active_name, "target": "/workspace"},
                        {"source": volume_source, "target": "/home/agent/.config/tool"},
                    ],
                    "network": {"allow": []},
                    "resources": {"cpus": 0.5, "memory": "256m", "pids": 64},
                }
            )
        )
        run("abx", "start", str(cfg))
        run(
            "abx",
            "exec",
            env,
            "--",
            "sh",
            "-c",
            "printf agent-code > /workspace/agent-file; chmod 600 /workspace/agent-file",
        )
        run("abx", "exec", env, "--", "ln", "-s", str(protected), "/workspace/link")
        assert (active / "agent-file").stat().st_uid == service_uid
        assert (active / "link").lstat().st_uid == service_uid
        script = Path(__file__).resolve().parents[2] / "scripts/uninstall.sh"
        preview = run("sudo", "bash", str(script), "--dry-run")
        assert "dry_run" in preview.stdout
        assert pwd.getpwnam("agentbox").pw_uid == service_uid
        assert (active / "agent-file").stat().st_uid == service_uid
        assert json.loads(run("abx", "--json", "status").stdout)["data"][env]["status"] == "running"
        result = run("sudo", "bash", str(script))
        assert "will be stopped" in result.stdout
        assert "Agentbox removed" in result.stdout
        assert (active / "agent-file").stat().st_uid == operator_uid
        assert (active / "agent-file").read_text() == "agent-code"
        assert (revoked / "retained").stat().st_uid == operator_uid
        assert (revoked / "retained").read_text() == "retained"
        assert (active / "developer-file").read_text() == "keep developer code"
        assert (active / "link").lstat().st_uid == operator_uid
        assert protected.stat().st_uid == protected_identity.st_uid
        assert protected.stat().st_ino == protected_identity.st_ino
        after_parent_acl = run("getfacl", "-cpn", str(parent)).stdout
        assert f"user:{service_uid}:" not in after_parent_acl
        assert "user:65534:--x" in after_parent_acl
        assert before_parent_acl.replace(f"user:{service_uid}:--x\n", "") == after_parent_acl
        for path in (active, active / "agent-file", revoked, revoked / "retained"):
            assert f"user:{service_uid}:" not in run("getfacl", "-cpn", str(path)).stdout
        with pytest.raises(KeyError):
            pwd.getpwnam("agentbox")
        for path in (
            "/opt/agentbox",
            "/etc/agentbox",
            "/var/lib/agentbox",
            "/var/lib/agentbox-operator",
            "/etc/sudoers.d/agentbox",
            "/etc/systemd/user/agentbox-watch.service",
            "/usr/local/bin/abx",
            "/usr/local/bin/agentbox",
            "/usr/local/libexec/agentbox-control",
            "/usr/local/libexec/agentbox-watch",
            "/usr/local/share/bash-completion/completions/abx",
            "/usr/local/share/bash-completion/completions/agentbox",
            f"/etc/systemd/system/user@{service_uid}.service.d/agentbox.conf",
            "/var/lib/systemd/linger/agentbox",
        ):
            run("sudo", "test", "!", "-e", path)
            run("sudo", "test", "!", "-L", path)
        for path in ("/etc/subuid", "/etc/subgid"):
            assert not any(
                line.split(":", 1)[0] in ("agentbox", str(service_uid))
                for line in Path(path).read_text().splitlines()
            )
        # Coexisting rootful Docker and its daemon identity remain untouched.
        assert (
            run(
                "sudo",
                "docker",
                "--host",
                "unix:///var/run/docker.sock",
                "info",
                "--format",
                "{{.ID}}",
            ).stdout.strip()
            == rootful_id
        )
        assert (
            run(
                "sudo",
                "docker",
                "--host",
                "unix:///var/run/docker.sock",
                "volume",
                "inspect",
                rootful_volume,
            ).stdout
            == rootful_before
        )

    finally:
        errors = []

        def cleanup(*arguments):
            try:
                result = run(*arguments, check=False)
                if result.returncode:
                    errors.append(f"{arguments}: {result.stderr}")
            except (OSError, subprocess.SubprocessError) as exc:
                errors.append(str(exc))

        if run("mountpoint", "-q", str(mount), check=False).returncode == 0:
            cleanup("sudo", "umount", str(mount))
        if Path("/usr/local/bin/abx").exists():
            cleanup("abx", "remove", env)
            listed = run("abx", "--json", "mount", "list", check=False)
            if listed.returncode:
                errors.append(listed.stderr)
            else:
                entries = json.loads(listed.stdout)["data"]
                for name in registered:
                    if name in entries and entries[name]["status"] != "revoked":
                        cleanup("abx", "mount", "revoke", name)
        cleanup(
            "sudo",
            "docker",
            "--host",
            "unix:///var/run/docker.sock",
            "volume",
            "rm",
            rootful_volume,
        )
        if errors:
            pytest.fail("Uninstall cleanup failed:\n" + "\n".join(errors))
        shutil.rmtree(parent)
