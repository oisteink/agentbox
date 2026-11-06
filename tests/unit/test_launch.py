"""Exact Docker exec identity and raw nullable status form the launch barrier."""

import json
import os
import time
from types import SimpleNamespace

import pytest

from agentbox.errors import AgentboxError
from agentbox.runtime import Docker

AGENT = "a" * 64
EXEC = "e" * 64


@pytest.mark.parametrize(
    "detail,valid",
    [
        ({"Pid": 123, "Running": True, "ExitCode": None}, True),
        ({"Pid": 123, "Running": False, "ExitCode": 0}, True),
        ({"Pid": 0, "Running": False, "ExitCode": 126}, True),
        ({"Pid": 0, "Running": False, "ExitCode": 0}, True),
        ({"Pid": True, "Running": True, "ExitCode": None}, False),
        ({"Pid": 0, "Running": False, "ExitCode": False}, False),
        ({"Pid": 0, "Running": False, "ExitCode": None}, False),
        ({"Pid": 0, "Running": True, "ExitCode": 0}, False),
    ],
)
def test_launch_requires_pid_or_final_typed_exit(monkeypatch, detail, valid):
    docker = Docker(os.getuid(), "/unused")
    intent = {"agent": AGENT, "baseline": [], "since": time.time_ns(), "exec": EXEC}
    monkeypatch.setattr(
        docker, "exec_inspect", lambda *args: dict(detail, ID=EXEC, ContainerID=AGENT)
    )
    if valid:
        docker.confirm_launch(intent, time.monotonic() + 0.05, lambda: None)
    else:
        with pytest.raises(AgentboxError) as error:
            docker.confirm_launch(intent, time.monotonic() + 0.025, lambda: None)
        assert error.value.code == "launch_unknown"


@pytest.mark.parametrize("wrong", ["ID", "ContainerID"])
def test_other_exec_or_container_never_releases_barrier(monkeypatch, wrong):
    docker = Docker(os.getuid(), "/unused")
    detail = {"ID": EXEC, "ContainerID": AGENT, "Pid": 123, "Running": True, "ExitCode": None}
    detail[wrong] = "f" * 64
    monkeypatch.setattr(docker, "exec_inspect", lambda *args: detail)
    with pytest.raises(AgentboxError, match="identity changed"):
        docker.confirm_launch({"agent": AGENT, "exec": EXEC}, time.monotonic() + 1, lambda: None)


def test_fast_exit_can_be_identified_by_event_replay(monkeypatch):
    docker = Docker(os.getuid(), "/unused")
    calls = []
    saved = []

    def run(*args, **kwargs):
        calls.append((args, kwargs["timeout"]))
        if args[0] == "container":
            return SimpleNamespace(stdout="[]")
        return SimpleNamespace(
            stdout=json.dumps(
                {
                    "Action": "exec_create: true",
                    "Actor": {"ID": AGENT, "Attributes": {"execID": EXEC}},
                }
            )
        )

    monkeypatch.setattr(docker, "run", run)
    monkeypatch.setattr(
        docker,
        "exec_inspect",
        lambda *args: {
            "ID": EXEC,
            "ContainerID": AGENT,
            "Pid": 321,
            "Running": False,
            "ExitCode": 0,
        },
    )
    intent = {"agent": AGENT, "baseline": [], "since": time.time_ns(), "exec": None}
    docker.confirm_launch(intent, time.monotonic() + 1, lambda: saved.append(intent["exec"]))
    assert saved == [EXEC] and calls[1][0][0] == "events"
    assert all(0 < timeout <= 1 for _, timeout in calls)


def test_ambiguous_new_execs_are_not_guessed(monkeypatch):
    docker = Docker(os.getuid(), "/unused")
    monkeypatch.setattr(
        docker, "run", lambda *args, **kwargs: SimpleNamespace(stdout=json.dumps([EXEC, "f" * 64]))
    )
    with pytest.raises(AgentboxError, match="ambiguous"):
        docker.confirm_launch(
            {"agent": AGENT, "baseline": [], "exec": None},
            time.monotonic() + 1,
            lambda: pytest.fail("Ambiguous ID persisted"),
        )


def test_raw_http_json_keeps_null_and_uses_fixed_socket(monkeypatch):
    docker = Docker(os.getuid(), "/unused")
    observed = []
    wire = SimpleNamespace(
        settimeout=lambda seconds: None,
        connect=lambda path: observed.append(path),
        close=lambda: None,
    )

    class Connection:
        def __init__(self, *args, **kwargs):
            self.sock = None

        def request(self, method, path):
            observed.append((method, path))

        def getresponse(self):
            blocks = iter([b'{"ExitCode":null,"Pid":0,"Running":false}', b""])
            return SimpleNamespace(status=200, read1=lambda size: next(blocks))

        def close(self):
            pass

    monkeypatch.setattr("agentbox.runtime.socket.socket", lambda *args: wire)
    monkeypatch.setattr("agentbox.runtime.http.client.HTTPConnection", Connection)
    result = docker._json_get("/v1.48/exec/" + EXEC + "/json", time.monotonic() + 1)
    assert result["ExitCode"] is None
    assert observed[0] == str(docker.socket) and observed[1][0] == "GET"
