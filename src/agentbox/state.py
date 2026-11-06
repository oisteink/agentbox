"""Private, atomic state with an installation-wide operation lock."""

import fcntl
import json
import os
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from .errors import AgentboxError


def atomic_json(path, data):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".agentbox-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(data, file, indent=2, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Store:
    def __init__(self, path):
        self.root = Path(path)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = self.root.stat()
        if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
            raise AgentboxError("State directory must be owned by the service user with mode 0700")

    @contextmanager
    def locked(self):
        fd = os.open(self.root / "lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            path = self.root / "state.json"
            data = (
                json.loads(path.read_text())
                if path.exists()
                else {
                    "schema": 2,
                    "installation": uuid.uuid4().hex,
                    "mounts": {},
                    "environments": {},
                }
            )
            if data.get("schema") != 2:
                raise AgentboxError("Unsupported state schema")
            yield data
            atomic_json(path, data)
        finally:
            os.close(fd)
