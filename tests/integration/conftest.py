"""Function-scoped resources for installed tests in the disposable lab."""

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


def cli(*arguments, check=True, **kwargs):
    """Use the public machine interface for metadata; preserve process assertions."""
    metadata = arguments[0] not in ("run", "shell", "exec", "logs", "completion") and not (
        arguments[:2] == ("image", "edit")
    )
    result = subprocess.run(
        ["/usr/local/bin/abx", *(["--json"] if metadata else []), *arguments],
        check=False,
        text=True,
        capture_output=True,
        timeout=kwargs.pop("timeout", 120),
        **kwargs,
    )
    if metadata:
        frames = [json.loads(line) for line in result.stdout.splitlines()]
        final = frames[-1]
        assert final["type"] == "result", frames
        result.stdout = json.dumps(final.get("data"))
        result.stderr += "".join(
            frame["data"] for frame in frames[:-1] if frame["type"] == "output"
        )
        if not final["ok"]:
            result.returncode = 2
            result.stderr += final["error"]["message"]
    if check:
        result.check_returncode()
    return result


class Lab:
    def __init__(self, root):
        self.root = root
        self.suffix = uuid.uuid4().hex[:8]
        self.projects = {}
        self.environments = {}
        self.images = {}

    def image(self):
        name = "image-" + self.suffix
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        path = root / "agentbox/images" / name
        self.images[name] = path
        cli("image", "new", name)
        return name, path

    def project(self, label="project"):
        name = f"{label}-{self.suffix}"
        path = self.root / name
        path.mkdir()
        self.projects[name] = path  # Track before a command can partially succeed.
        result = json.loads(cli("project", "add", name, "--path", str(path)).stdout)
        assert result["status"] == "active"
        return name, path

    def configuration(self, project, *, image="smoke", **overrides):
        name = f"env-{len(self.environments)}-{self.suffix}"
        path = self.root / f"{name}.yaml"  # Outside the shared project.
        config = {
            "name": name,
            "image": image,
            "mounts": [{"project": project, "target": "/workspace"}],
            "network": {"allow": []},
            "resources": {"cpus": 0.5, "memory": "256m", "pids": 64},
        } | overrides
        path.write_text(yaml.safe_dump(config))
        self.environments[name] = path
        return name, path

    def start(self, project, *, image="smoke", **overrides):
        name, path = self.configuration(project, image=image, **overrides)
        assert json.loads(cli("start", str(path)).stdout)["status"] == "running"
        return name

    def state(self, name):
        return json.loads(cli("status").stdout)[name]

    def assert_removed(self, name):
        assert name not in json.loads(cli("status").stdout), f"State retained for {name}"
        uid = pwd.getpwnam("agentbox").pw_uid
        for kind in ("container", "network"):
            arguments = [kind, "ls", "-q", "--filter", f"label=agentbox.environment={name}"]
            if kind == "container":
                arguments.append("-a")
            remaining = subprocess.run(
                [
                    "sudo",
                    "-u",
                    "agentbox",
                    "env",
                    "-i",
                    "PATH=/usr/bin:/bin",
                    "HOME=/var/lib/agentbox",
                    f"XDG_RUNTIME_DIR=/run/user/{uid}",
                    "docker",
                    "--host",
                    f"unix:///run/user/{uid}/docker.sock",
                    *arguments,
                ],
                check=True,
                text=True,
                capture_output=True,
                timeout=30,
            )
            assert not remaining.stdout.strip(), f"Leaked {kind} for {name}: {remaining.stdout}"

    def cleanup(self):
        errors = []
        for name in reversed(self.environments):
            try:
                result = cli("remove", name, check=False)
                if result.returncode:
                    errors.append(f"remove {name}: {result.stderr}")
                else:
                    self.assert_removed(name)
            except (AssertionError, OSError, subprocess.SubprocessError, ValueError) as exc:
                errors.append(f"remove {name}: {exc}")
        try:
            registered = json.loads(cli("project", "list").stdout)
            for name in reversed(self.projects):
                if name not in registered or registered[name]["status"] == "revoked":
                    continue
                try:
                    result = cli("project", "revoke", name, check=False)
                    if result.returncode:
                        errors.append(f"revoke {name}: {result.stderr}")
                except (OSError, subprocess.SubprocessError) as exc:
                    errors.append(f"revoke {name}: {exc}")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            errors.append(f"list projects: {exc}")
        for name, path in self.images.items():
            try:
                details = json.loads(cli("image", "inspect", name).stdout)
                if details["id"]:
                    cli("image", "rm", name)
                assert json.loads(cli("image", "inspect", name).stdout)["id"] is None
                shutil.rmtree(path)
            except (AssertionError, OSError, subprocess.SubprocessError, ValueError) as exc:
                errors.append(f"remove image {name}: {exc}")
        if errors:
            pytest.fail(f"Lab cleanup failed; files retained at {self.root}:\n" + "\n".join(errors))
        shutil.rmtree(self.root)


@pytest.fixture
def lab():
    if os.environ.get("AGENTBOX_LAB") != "1":
        pytest.skip("requires AGENTBOX_LAB=1 in the disposable lab")
    if socket.gethostname() != "agentbox-lab":
        pytest.fail("Refusing installed tests outside disposable agentbox-lab")
    if os.getuid() != pwd.getpwnam("developer").pw_uid:
        pytest.fail("Run installed tests as the lab developer")
    resources = Lab(Path(tempfile.mkdtemp(prefix="agentbox-test-", dir=Path.home())))
    try:
        yield resources
    finally:
        resources.cleanup()
