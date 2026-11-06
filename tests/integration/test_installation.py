"""Installer acceptance in the disposable lab; image creation and reuse."""

import json
import os
import pwd
import shutil
import subprocess
from pathlib import Path


def test_proxy_image_installation_and_build_failure(lab):
    source = Path(__file__).resolve().parents[2]
    broken = lab.root / "broken-source"
    for directory in ("src", "proxy", "security", "images", "scripts"):
        shutil.copytree(
            source / directory,
            broken / directory,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    (broken / "proxy/Dockerfile").write_text("INVALID_DOCKERFILE\n")
    uid = pwd.getpwnam("agentbox").pw_uid
    operator = pwd.getpwuid(os.getuid()).pw_name
    settings = json.loads(Path("/etc/agentbox/settings.json").read_text())
    image = settings["proxy_image"]

    def docker(*arguments):
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
                "/usr/bin/docker",
                "--host",
                f"unix:///run/user/{uid}/docker.sock",
                *arguments,
            ],
            text=True,
            capture_output=True,
            check=True,
            timeout=120,
        ).stdout.strip()

    def install(root, *, check=True):
        return subprocess.run(
            ["sudo", "bash", str(root / "scripts/install.sh"), "--operator", operator],
            text=True,
            capture_output=True,
            check=check,
            timeout=1200,
        )

    original = docker("image", "inspect", "--format", "{{.Id}}", image)
    container = None
    try:
        container = docker("container", "create", "--network", "none", image)
        bundled = Path("/opt/agentbox/lib/agentbox/templates/base/Dockerfile")
        expected_template = (source / "src/agentbox/templates/base/Dockerfile").read_bytes()
        user_recipe = Path.home() / ".config/agentbox/images/codex/Dockerfile"
        expected_user = user_recipe.read_bytes()
        subprocess.run(
            ["sudo", "tee", str(bundled)],
            input="INVALID_TEMPLATE\n",
            text=True,
            capture_output=True,
            check=True,
            timeout=30,
        )
        stale = Path("/opt/agentbox/lib/agentbox/stale_module.py")
        subprocess.run(["sudo", "touch", str(stale)], check=True, timeout=30)
        assert install(broken).returncode == 0
        assert not stale.exists()
        assert bundled.read_bytes() == expected_template
        assert user_recipe.read_bytes() == expected_user
        assert docker("image", "inspect", "--format", "{{.Id}}", image) == original
        docker("container", "rm", container)
        container = None
        docker("image", "rm", image)
        failed = install(broken, check=False)
        assert failed.returncode != 0
        assert "INVALID_DOCKERFILE" in failed.stderr
        assert "Installed. Run as the developer:" not in failed.stdout
        assert not docker("image", "ls", "-q", image)
    finally:
        try:
            if container is not None:
                docker("container", "rm", container)
        finally:
            install(source)
            assert docker("image", "inspect", "--format", "{{.Id}}", image)
            assert (
                Path("/opt/agentbox/proxy/Dockerfile").read_bytes()
                == (source / "proxy/Dockerfile").read_bytes()
            )
