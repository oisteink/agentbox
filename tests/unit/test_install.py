"""Exercise installer user selection, stopping before privileged setup begins."""

import os
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).resolve().parents[2] / "scripts/install.sh"


@pytest.mark.parametrize(
    "sudo_user,args,code,message",
    [
        ("alice", [], 42, "selected:alice"),
        ("alice", ["--operator", "bob"], 42, "selected:bob"),
        (None, ["--operator", "bob"], 42, "selected:bob"),
        (None, [], 2, "Cannot infer the developer"),
        ("root", [], 1, "Choose a regular developer"),
        ("agentbox", [], 1, "Choose a regular developer"),
        ("alice", ["--operator"], 2, "Usage:"),
        ("alice", ["--operator", "bad;name"], 2, "Invalid operator username"),
        (None, ["--help"], 0, "Defaults to the user invoking sudo"),
    ],
)
def test_installer_selects_operator(tmp_path, sudo_user, args, code, message):
    executable = tmp_path / "id"
    executable.write_text(
        "#!/bin/bash\n"
        "if [[ $# == 1 ]]; then echo 0; exit 0; fi\n"
        'case "$2" in\n'
        "  root) echo 0 ;;\n"
        "  agentbox) echo 1001 ;;\n"
        '  *) echo "selected:$2" >&2; exit 42 ;;\n'
        "esac\n"
    )
    executable.chmod(0o755)
    env = dict(os.environ, PATH=f"{tmp_path}:/usr/bin:/bin")
    env.pop("SUDO_USER", None)
    if sudo_user is not None:
        env["SUDO_USER"] = sudo_user
    result = subprocess.run(
        ["bash", str(INSTALLER), *args], env=env, text=True, capture_output=True, timeout=5
    )
    assert result.returncode == code
    assert message in result.stdout + result.stderr
