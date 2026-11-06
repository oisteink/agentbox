"""Bash completion support; dynamic lookups never prompt for sudo credentials."""

import json
import subprocess
from pathlib import Path

from . import config, images
from .errors import AgentboxError


def bash_script():
    return (Path(__file__).parent / "completions" / "abx.bash").read_text()


def names(kind):
    if kind == "images":
        try:
            return images.names()
        except OSError:
            return []
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
        {"action": "status"} if kind == "environments" else {"action": "mount", "operation": "list"}
    )
    try:
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", "-H", "-u", "agentbox", "/usr/local/libexec/agentbox-control"],
            input=json.dumps(request) + "\n",
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
        if result.returncode:
            return []
        frame = json.loads(result.stdout)
        if not isinstance(frame, dict) or frame.get("type") != "result" or not frame.get("ok"):
            return []
        entries = frame.get("data")
        if not isinstance(entries, dict):
            return []
        return sorted(config.name(name) for name in entries)
    except (OSError, ValueError, AgentboxError, subprocess.SubprocessError):
        return []
