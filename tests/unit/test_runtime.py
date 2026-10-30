import json
import os
import stat
from types import SimpleNamespace

import pytest

from agentbox.errors import AgentboxError
from agentbox.runtime import Docker


@pytest.fixture
def daemon(monkeypatch):
    uid = os.getuid()
    monkeypatch.setattr(
        "pathlib.Path.lstat",
        lambda path: SimpleNamespace(st_uid=uid, st_mode=stat.S_IFSOCK | 0o660),
    )
    info = {
        "ID": "expected",
        "SecurityOptions": ["name=rootless"],
        "CgroupVersion": "2",
        "CgroupDriver": "systemd",
        "DockerRootDir": "/var/lib/agentbox/data",
        "ServerVersion": "29.9.2",
        "Warnings": [],
    }
    docker = Docker(uid, "/var/lib/agentbox")
    monkeypatch.setattr(docker, "run", lambda *args: SimpleNamespace(stdout=json.dumps(info)))
    return docker, info


def test_rootful_daemon_rejected(daemon):
    docker, info = daemon
    info["SecurityOptions"] = []
    with pytest.raises(AgentboxError, match="not rootless"):
        docker.verify()


def test_changed_daemon_id_rejected(daemon):
    with pytest.raises(AgentboxError, match="ID changed"):
        daemon[0].verify("different")


def test_missing_cgroups_rejected(daemon):
    docker, info = daemon
    info["CgroupDriver"] = "none"
    with pytest.raises(AgentboxError, match="cgroup"):
        docker.verify()


def test_daemon_environment_is_not_inherited(monkeypatch):
    monkeypatch.setenv("DOCKER_HOST", "tcp://unexpected:2375")
    monkeypatch.setenv("DOCKER_CONTEXT", "rootful")
    monkeypatch.setenv("OPENAI_API_KEY", "test-do-not-inherit")
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("agentbox.runtime.subprocess.run", run)
    Docker(1001, "/var/lib/agentbox").run("version")
    assert seen["command"][:3] == ["/usr/bin/docker", "--host", "unix:///run/user/1001/docker.sock"]
    assert "DOCKER_HOST" not in seen["env"]
    assert "DOCKER_CONTEXT" not in seen["env"]
    assert "OPENAI_API_KEY" not in seen["env"]
