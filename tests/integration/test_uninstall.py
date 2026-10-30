"""Destructive uninstall acceptance test: explicitly opt in inside the disposable VM."""

import json
import os
import pwd
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


def test_full_uninstall_keeps_projects_and_returns_ownership():
    service_uid = pwd.getpwnam("agentbox").pw_uid
    run(
        "sudo",
        "-u",
        "agentbox",
        "docker",
        "--host",
        f"unix:///run/user/{service_uid}/docker.sock",
        "tag",
        "agentbox-proxy:lab",
        "agentbox-proxy:local",
    )
    operator_uid = os.getuid()
    token = uuid.uuid4().hex[:8]
    rootful_id = run(
        "sudo", "docker", "--host", "unix:///var/run/docker.sock", "info", "--format", "{{.ID}}"
    ).stdout.strip()
    active_name, revoked_name = "active-" + token, "revoked-" + token
    env = "uninstall-" + token
    with tempfile.TemporaryDirectory(prefix="agentbox-uninstall-", dir=Path.home()) as temp:
        parent = Path(temp)
        active, revoked, outside = (parent / name for name in ("active", "revoked", "outside"))
        for path in (active, revoked, outside):
            path.mkdir()
        protected = outside / "protected"
        protected.write_text("outside content")
        run("sudo", "chown", "root:root", str(protected))
        protected_identity = protected.stat()
        (active / "developer-file").write_text("keep developer code")
        for name, path in ((active_name, active), (revoked_name, revoked)):
            run("agentbox", "project", "add", name, "--path", str(path))
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
        run("agentbox", "project", "revoke", revoked_name)
        # Manual ancestor ACL edits must survive uninstall.
        run("setfacl", "-m", "u:65534:--x", str(parent))
        before_parent_acl = run("getfacl", "-cpn", str(parent)).stdout
        mount = active / "nested"
        mount.mkdir()
        run("sudo", "mount", "--bind", str(outside), str(mount))
        try:
            cfg = parent / "environment.yaml"
            cfg.write_text(
                yaml.safe_dump(
                    {
                        "name": env,
                        "image": "agentbox-dev:lab",
                        "command": ["bash"],
                        "mounts": [{"project": active_name, "target": "/workspace"}],
                        "network": {"allow": []},
                        "resources": {"cpus": 0.5, "memory": "256m", "pids": 64},
                    }
                )
            )
            run("agentbox", "start", str(cfg))
            run(
                "agentbox",
                "exec",
                env,
                "--",
                "sh",
                "-c",
                "printf agent-code > /workspace/agent-file; chmod 600 /workspace/agent-file",
            )
            run("agentbox", "exec", env, "--", "ln", "-s", str(protected), "/workspace/link")
            assert (active / "agent-file").stat().st_uid == service_uid
            assert (active / "link").lstat().st_uid == service_uid
            script = Path(__file__).resolve().parents[2] / "scripts/uninstall.sh"
            preview = run("sudo", "bash", str(script), "--dry-run")
            assert "dry_run" in preview.stdout
            assert pwd.getpwnam("agentbox").pw_uid == service_uid
            assert (active / "agent-file").stat().st_uid == service_uid
            assert json.loads(run("agentbox", "status").stdout)[env]["status"] == "running"
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
                "/usr/local/bin/agentbox",
                "/usr/local/libexec/agentbox-control",
                "/usr/local/libexec/agentbox-watch",
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
        finally:
            run("sudo", "umount", str(mount), check=False)
            if Path("/usr/local/bin/agentbox").exists():
                run("agentbox", "remove", env, check=False)
                run("agentbox", "project", "revoke", active_name, check=False)
