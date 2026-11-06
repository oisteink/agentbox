import os
import subprocess
import sys
import time

import pytest

from agentbox import sessions
from agentbox.errors import AgentboxError


def test_process_identity_distinguishes_reuse_uid_and_boot():
    current = sessions.identity()
    assert sessions.client(current, os.getuid()) == current and sessions.alive(current)
    for key, value in (("start", -1), ("boot", "other-boot"), ("uid", os.getuid() + 1)):
        assert not sessions.alive(dict(current, **{key: value}))
    with pytest.raises(AgentboxError):
        sessions.client(dict(current, pid=True), os.getuid())
    with pytest.raises(AgentboxError):
        sessions.client(current, os.getuid() + 1)


def test_exited_unreaped_child_is_dead():
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    try:
        deadline = time.monotonic() + 2
        while sessions.identity(child.pid) is not None:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert child.wait(timeout=1) == 0
    finally:
        if child.poll() is None:
            child.kill()
            child.wait()
