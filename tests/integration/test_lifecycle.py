"""Installed-CLI acceptance checks. Run as developer in the disposable lab only."""

import json
import os
import pwd
import shlex
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.skipif(
    os.environ.get("AGENTBOX_LAB") != "1" or socket.gethostname() != "agentbox-lab",
    reason="requires installed agentbox in the disposable lab",
)


def cli(*arguments, check=True):
    return subprocess.run(
        ["/usr/local/bin/agentbox", *arguments],
        check=check,
        text=True,
        capture_output=True,
        timeout=120,
    )


def test_two_environments_and_revocation():
    token = uuid.uuid4().hex[:8]
    first, second = "first-" + token, "second-" + token
    env1, env2 = "env-first-" + token, "env-second-" + token
    registered = []
    environments = []
    with tempfile.TemporaryDirectory(prefix="agentbox-lifecycle-", dir=Path.home()) as temporary:
        root = Path(temporary)
        project1, project2, hidden = (root / p for p in ("one", "two", "hidden"))
        for project in (project1, project2, hidden):
            project.mkdir()
        (hidden / "private.txt").write_text("not shared")
        (project1 / "from-developer").write_text("original")
        (project2 / "readonly").write_text("unchanged")
        try:
            for name, project in ((first, project1), (second, project2)):
                result = json.loads(cli("project", "add", name, "--path", str(project)).stdout)
                assert result["status"] == "active"
                registered.append(name)
            for environment, project_name, image in (
                (env1, first, "agentbox-dev:local"),
                (env2, second, "agentbox-dev:lab"),
            ):
                cfg = {
                    "name": environment,
                    "image": image,
                    "command": ["bash"],
                    "mounts": [{"project": project_name, "target": "/workspace"}],
                    "network": {"allow": []},
                    "resources": {"cpus": 0.5, "memory": "256m", "pids": 64},
                }
                if environment == env1:
                    cfg["mounts"].append({"project": second, "target": "/readonly", "mode": "ro"})
                path = root / (environment + ".yaml")
                path.write_text(yaml.safe_dump(cfg))
                result = json.loads(cli("start", environment, "--config", str(path)).stdout)
                assert result["status"] == "running"
                environments.append(environment)
            assert (
                json.loads(cli("project", "add", first, "--path", str(project1)).stdout)["status"]
                == "active"
            )
            assert (
                cli("exec", env1, "--", "codex", "--version")
                .stdout.strip()
                .endswith("codex-cli 0.166.0")
            )
            terminal = subprocess.run(
                [
                    "script",
                    "-q",
                    "-e",
                    "-c",
                    shlex.join(
                        [
                            "/usr/local/bin/agentbox",
                            "exec",
                            env1,
                            "--",
                            "bash",
                            "-c",
                            "test -t 0 && printf tty-ok",
                        ]
                    ),
                    "/dev/null",
                ],
                input="",
                text=True,
                capture_output=True,
                timeout=30,
            )
            assert terminal.returncode == 0, terminal.stdout + terminal.stderr
            assert "tty-ok" in terminal.stdout
            cli("exec", env1, "--", "bash", "-c", "printf agent > /workspace/from-agent")
            assert (project1 / "from-agent").read_text() == "agent"
            with (project1 / "from-agent").open("a") as file:
                file.write("-developer")
            assert (
                cli("exec", env1, "--", "cat", "/workspace/from-agent").stdout == "agent-developer"
            )
            assert cli("exec", env1, "--", "test", "-e", str(hidden), check=False).returncode != 0
            assert cli("exec", env1, "--", "cat", "/readonly/readonly").stdout == "unchanged"
            assert (
                cli(
                    "exec",
                    env1,
                    "--",
                    "python3",
                    "-c",
                    "open('/readonly/readonly', 'w').write('bad')",
                    check=False,
                ).returncode
                != 0
            )
            assert (
                cli(
                    "exec", env1, "--", "test", "-S", "/var/run/docker.sock", check=False
                ).returncode
                != 0
            )
            assert (
                cli(
                    "exec",
                    env1,
                    "--",
                    "ip",
                    "link",
                    "add",
                    "forbidden",
                    "type",
                    "dummy",
                    check=False,
                ).returncode
                != 0
            )
            assert (
                cli(
                    "exec", env1, "--", "cat", "/proc/sys/net/ipv6/conf/all/disable_ipv6"
                ).stdout.strip()
                == "1"
            )
            # A live service in environment two is reachable from itself, but not environment one.
            cli(
                "exec",
                env2,
                "--",
                "bash",
                "-c",
                "python3 -m http.server 18482 >/tmp/test-http.log 2>&1 & echo started",
            )
            control = cli(
                "exec",
                env2,
                "--",
                "curl",
                "--fail",
                "--silent",
                "--noproxy",
                "*",
                "--retry",
                "3",
                "--retry-connrefused",
                "http://127.0.0.1:18482/",
            )
            assert "readonly" in control.stdout
            address = cli(
                "exec",
                env2,
                "--",
                "python3",
                "-c",
                "import socket; print(socket.gethostbyname(socket.gethostname()))",
            ).stdout.strip()
            cross_environment = cli(
                "exec",
                env1,
                "--",
                "python3",
                "-c",
                "import socket; socket.create_connection((" + repr(address) + ",18482),timeout=2)",
                check=False,
            )
            assert cross_environment.returncode != 0
            cli("stop", env2)
            assert (
                cli("project", "revoke", second, check=False).returncode != 0
            )  # env1 has a read-only mount.
            cli("start", env2, "--config", str(root / (env2 + ".yaml")))
            # New Unix sockets are blocked at syscall creation, independently of directory scans.
            denied = cli(
                "exec",
                env1,
                "--",
                "python3",
                "-c",
                "import socket; socket.socket(socket.AF_UNIX)",
                check=False,
            )
            assert denied.returncode != 0
            cli(
                "exec", env1, "--", "python3", "-c", "import asyncio; asyncio.run(asyncio.sleep(0))"
            )
            # Resource settings observed inside the container must match the requested limits.
            output = cli(
                "exec",
                env1,
                "--",
                "python3",
                "-c",
                "import pathlib,json; p=pathlib.Path('/sys/fs/cgroup'); "
                "print(json.dumps({n:(p/n).read_text().strip() "
                "for n in ['cpu.max','memory.max','pids.max']}))",
            )
            limits = json.loads(output.stdout)
            assert limits == {
                "cpu.max": "50000 100000",
                "memory.max": "268435456",
                "pids.max": "64",
            }
            blocked = cli("project", "revoke", first, check=False)
            assert blocked.returncode != 0  # Running mounts must prevent revocation.
            cli("exec", env1, "--", "chmod", "0600", "/workspace/from-agent")
            with pytest.raises(PermissionError):
                (project1 / "from-agent").read_text()
            checked = json.loads(cli("project", "check", first).stdout)
            assert "from-agent" in checked["operator_access_issues"]
            cli("stop", env1)
            cli("stop", env1)
            cli("project", "repair", first)
            assert (project1 / "from-agent").read_text() == "agent-developer"
            checked = json.loads(cli("project", "check", first).stdout)
            assert not checked["operator_access_issues"] and not checked["service_access_issues"]
            # Resuming an unchanged environment preserves its writable layer.
            cli("start", env1, "--config", str(root / (env1 + ".yaml")))
            assert (
                cli("exec", env1, "--", "cat", "/workspace/from-agent").stdout == "agent-developer"
            )
            assert "agent-developer" in cli("logs", env1).stdout
            cli("stop", env1)
            assert cli("exec", env2, "--", "cat", "/workspace/readonly").stdout == "unchanged"
            cli("remove", env1)
            environments.remove(env1)
            assert (project1 / "from-agent").read_text() == "agent-developer"
            result = json.loads(cli("project", "revoke", first).stdout)
            assert result["status"] == "revoked"
            registered.remove(first)
            # Another registered project remains active after shared-parent ACL cleanup.
            assert cli("exec", env2, "--", "cat", "/workspace/readonly").stdout == "unchanged"
            # An interrupted daemon must not turn start into an implicit remove.
            cli("exec", env2, "--", "bash", "-c", "printf retained > /home/agent/retained")
            uid = pwd.getpwnam("agentbox").pw_uid
            subprocess.run(
                [
                    "sudo",
                    "-u",
                    "agentbox",
                    "env",
                    "HOME=/var/lib/agentbox",
                    f"XDG_RUNTIME_DIR=/run/user/{uid}",
                    f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
                    "systemctl",
                    "--user",
                    "restart",
                    "docker.service",
                ],
                check=True,
                text=True,
                capture_output=True,
                timeout=45,
            )
            for attempt in range(20):
                resumed = cli("start", env2, "--config", str(root / (env2 + ".yaml")), check=False)
                if resumed.returncode == 0:
                    break
                time.sleep(0.2)
            else:
                raise AssertionError(resumed.stderr)
            assert cli("exec", env2, "--", "cat", "/home/agent/retained").stdout == "retained"
        finally:
            for environment in reversed(environments):
                cli("remove", environment, check=False)
            for project in reversed(registered):
                cli("project", "revoke", project, check=False)
