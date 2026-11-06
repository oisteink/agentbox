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
    metadata = arguments[0] not in ("start", "run", "exec", "logs", "completion") and not (
        arguments[:2] == ("image", "edit")
    )
    if arguments[0] in ("start", "exec", "run"):
        kwargs.setdefault("input", "")
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
        result.stdout = json.dumps(
            final.get("data") if final["ok"] else final["error"].get("details")
        )
        result.stderr += "".join(
            frame["data"] for frame in frames[:-1] if frame["type"] == "output"
        )
        if not final["ok"]:
            result.returncode = 2
            result.stderr += final["error"]["message"]
    if check:
        result.check_returncode()
    return result


def machine(*args, **kwargs):
    result = subprocess.run(
        ["/usr/local/bin/abx", "--json", *args],
        capture_output=True,
        text=True,
        timeout=120,
        **kwargs,
    )
    assert result.returncode == 0 and result.stderr == "", result
    frames = [json.loads(line) for line in result.stdout.splitlines()]
    assert sum(frame["type"] == "result" for frame in frames) == 1
    assert frames[-1]["type"] == "result"
    return frames


class Lab:
    def __init__(self, root):
        self.root = root
        self.suffix = uuid.uuid4().hex[:8]
        self.mounts = {}
        self.environments = {}
        self.images = {}

    def image(self):
        name = "image-" + self.suffix
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        path = root / "agentbox/images" / name
        self.images[name] = path
        cli("image", "new", name)
        return name, path

    def mount(self, label="mount"):
        name = f"{label}-{self.suffix}"
        path = self.root / name
        path.mkdir()
        self.mounts[name] = path  # Track before a command can partially succeed.
        result = json.loads(cli("mount", "add", name, str(path)).stdout)
        assert result["status"] == "active"
        return name, path

    def volume(self, label="volume"):
        name = f"{label}-{self.suffix}"
        self.mounts[name] = None
        result = json.loads(cli("mount", "add", name, "--volume").stdout)
        assert result["type"] == "volume" and result["status"] == "active"
        return name

    def configuration(self, mount, *, image="smoke", **overrides):
        name = f"env-{len(self.environments)}-{self.suffix}"
        folder = (
            Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
            / "agentbox/environments"
        )
        folder.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = folder / f"{name}.yaml"  # Outside every shared mount.
        config = {
            "name": name,
            "image": image,
            "mounts": [{"source": mount, "target": "/workspace"}],
            "network": {"allow": []},
            "resources": {"cpus": 0.5, "memory": "256m", "pids": 64},
        } | overrides
        path.write_text(yaml.safe_dump(config))
        self.environments[name] = path
        return name, path

    def start(self, mount, *, image="smoke", **overrides):
        name, path = self.configuration(mount, image=image, **overrides)
        cli("start", str(path), "--keep-running")
        assert self.state(name)["status"] == "running"
        return name

    def state(self, name):
        return json.loads(cli("status").stdout)[name]

    def docker(self, *arguments, check=True):
        uid = pwd.getpwnam("agentbox").pw_uid
        return subprocess.run(
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
            check=check,
            text=True,
            capture_output=True,
            timeout=120,
        )

    def assert_removed(self, name):
        assert name not in json.loads(cli("status").stdout), f"State retained for {name}"
        for kind in ("container", "network"):
            arguments = [kind, "ls", "-q", "--filter", f"label=agentbox.environment={name}"]
            if kind == "container":
                arguments.append("-a")
            remaining = self.docker(*arguments)
            assert not remaining.stdout.strip(), f"Leaked {kind} for {name}: {remaining.stdout}"

    def cleanup(self):
        errors = []
        names = list(self.environments)
        try:
            names.extend(
                name
                for name in json.loads(cli("status").stdout)
                if any(
                    name.startswith(configured[:31] + "-run-") for configured in self.environments
                )
            )
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            errors.append(f"list temporary instances: {exc}")
        for name in reversed(names):
            try:
                result = cli("remove", name, check=False)
                if result.returncode:
                    errors.append(f"remove {name}: {result.stderr}")
                else:
                    self.assert_removed(name)
            except (AssertionError, OSError, subprocess.SubprocessError, ValueError) as exc:
                errors.append(f"remove {name}: {exc}")
        try:
            registered = json.loads(cli("mount", "list").stdout)
            for name in reversed(self.mounts):
                if name not in registered:
                    continue
                try:
                    result = cli("mount", "remove", name, "--yes", check=False)
                    if result.returncode:
                        errors.append(f"remove mount {name}: {result.stderr}")
                except (OSError, subprocess.SubprocessError) as exc:
                    errors.append(f"remove mount {name}: {exc}")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            errors.append(f"list mounts: {exc}")
        for name, path in self.images.items():
            try:
                details = json.loads(cli("image", "inspect", name).stdout)
                if details["id"]:
                    cli("image", "remove", name)
                assert json.loads(cli("image", "inspect", name).stdout)["id"] is None
                shutil.rmtree(path)
            except (AssertionError, OSError, subprocess.SubprocessError, ValueError) as exc:
                errors.append(f"remove image {name}: {exc}")
        if errors:
            pytest.fail(f"Lab cleanup failed; files retained at {self.root}:\n" + "\n".join(errors))
        for path in self.environments.values():
            path.unlink(missing_ok=True)
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
