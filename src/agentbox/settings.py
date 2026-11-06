"""Administrator-owned installation settings, never read from mount directories."""

import json
import os
import stat
from pathlib import Path

from .errors import AgentboxError

SETTINGS_PATH = Path("/etc/agentbox/settings.json")


def load_settings():
    try:
        fd = os.open(SETTINGS_PATH, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd) as file:
            meta = os.fstat(file.fileno())
            if meta.st_uid != 0 or meta.st_mode & 0o022 or not stat.S_ISREG(meta.st_mode):
                raise AgentboxError(
                    "Installation settings must be administrator-owned and not writable"
                )
            return json.load(file)
    except OSError as exc:
        raise AgentboxError("Run the documented administrator installation first") from exc
