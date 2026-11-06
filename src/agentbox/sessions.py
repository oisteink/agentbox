"""Linux process identities for active CLI sessions; no command or token data."""

import os
from pathlib import Path

from .errors import AgentboxError


def identity(pid=None):
    pid = os.getpid() if pid is None else pid
    try:
        directory = Path("/proc") / str(pid)
        value = (directory / "stat").read_text()
        fields = value[value.rfind(")") + 2 :].split()
        if fields[0] in ("Z", "X", "x"):
            return None
        return {
            "pid": pid,
            "start": int(fields[19]),
            "boot": Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
            "uid": directory.stat().st_uid,
        }
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (OSError, ValueError, IndexError):
        raise AgentboxError(
            "Cannot observe session process identity", code="process_observation_failed"
        ) from None


def alive(value):
    return identity(value["pid"]) == value


def client(value, operator_uid):
    if (
        not isinstance(value, dict)
        or set(value) != {"pid", "start", "boot", "uid"}
        or type(value["pid"]) is not int
        or value["pid"] <= 0
        or type(value["start"]) is not int
        or not isinstance(value["boot"], str)
        or type(value["uid"]) is not int
        or value["uid"] != operator_uid
        or not alive(value)
    ):
        raise AgentboxError("Expected the live operator CLI process", code="invalid_session")
    return value


def prune(runtime):
    dead = [
        key
        for key, session in runtime["sessions"].items()
        if not alive(session["client"]) or not alive(session["helper"])
    ]
    for key in dead:
        del runtime["sessions"][key]
    return dead
