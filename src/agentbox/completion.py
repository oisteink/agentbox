"""Bash completion support; dynamic lookups never prompt for sudo credentials."""

import json
import subprocess
from pathlib import Path

from . import config
from .errors import AgentboxError


def bash_script():
    return (Path(__file__).parent / "completions" / "abx.bash").read_text()


def names(kind):
    if kind == "configs":
        try:
            return sorted(
                {
                    path.stem
                    for suffix in ("*.yaml", "*.yml")
                    for path in config.environment_directory().glob(suffix)
                    if path.is_file() and config.NAME.fullmatch(path.stem)
                }
            )
        except OSError:
            return []
    request = (
        {"action": "status"}
        if kind == "environments"
        else {"action": "project", "operation": "list"}
    )
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", "-H", "-u", "agentbox", "/usr/local/libexec/agentbox-control"],
            input=json.dumps(request),
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
        if result.returncode:
            return []
        entries = json.loads(result.stdout)
        if not isinstance(entries, dict):
            return []
        return sorted(config.name(name) for name in entries)
    except (OSError, ValueError, AgentboxError, subprocess.SubprocessError):
        return []
