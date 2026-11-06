import fcntl
import os
import signal
from types import SimpleNamespace

import pytest

from agentbox.control import Control, defer_interrupts
from agentbox.errors import AgentboxError


@pytest.fixture
def temporary_control(tmp_path, monkeypatch):
    control = Control({"home": str(tmp_path), "service_uid": os.getuid()})
    removed = []

    def verified(data):
        data["daemon_id"] = "daemon"

    def start(data, payload, tokens):
        entry = {"resources": {"agent": "original"}}
        data["environments"][payload["name"]] = entry
        control.save(data)
        return entry

    def remove(data, name):
        removed.append(data["environments"][name]["resources"]["agent"])
        del data["environments"][name]
        control.save(data)

    def execute(*args, **kwargs):
        fd = os.open(control.store.root / "lock", os.O_RDWR)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        return 17

    monkeypatch.setattr(control, "verified", verified)
    monkeypatch.setattr(control, "start", start)
    monkeypatch.setattr(control, "remove", remove)
    control.docker = SimpleNamespace(verify=lambda identifier: None, exec_stream=execute)
    payload = {
        "name": "temporary",
        "image": "base",
        "command": ["bash"],
        "mounts": [{"project": "example", "target": "/workspace"}],
    }
    return control, payload, removed


def test_run_releases_lock_returns_exit_code_and_removes(temporary_control):
    control, payload, removed = temporary_control
    assert control.run(payload, {}) == 17
    assert removed == ["original"]
    with control.store.locked() as data:
        assert payload["name"] not in data["environments"]


def test_run_preserves_existing_environment(temporary_control):
    control, payload, removed = temporary_control
    with control.store.locked() as data:
        data["environments"][payload["name"]] = {"resources": {"agent": "existing"}}
    with pytest.raises(AgentboxError, match="already exists"):
        control.run(payload, {})
    assert removed == []


def test_run_cleanup_does_not_remove_replacement(temporary_control):
    control, payload, removed = temporary_control

    def replace(*args, **kwargs):
        with control.store.locked() as data:
            data["environments"][payload["name"]] = {"resources": {"agent": "replacement"}}
        return 0

    control.docker.exec_stream = replace
    with pytest.raises(AgentboxError, match="replacement kept"):
        control.run(payload, {})
    assert removed == []
    with control.store.locked() as data:
        assert data["environments"][payload["name"]]["resources"]["agent"] == "replacement"


def test_run_reports_cleanup_failure_over_command_success(temporary_control, monkeypatch):
    control, payload, _ = temporary_control
    control.docker.exec_stream = lambda *a, **kw: 0

    def fail(*args):
        raise AgentboxError("removal denied")

    monkeypatch.setattr(control, "remove", fail)
    with pytest.raises(AgentboxError, match="cleanup failed.*removal denied"):
        control.run(payload, {})


def test_run_cleans_partial_start_failure(temporary_control, monkeypatch):
    control, payload, removed = temporary_control
    original = control.start

    def fail(data, payload, tokens):
        original(data, payload, tokens)
        raise AgentboxError("start failed")

    monkeypatch.setattr(control, "start", fail)
    with pytest.raises(AgentboxError, match="start failed"):
        control.run(payload, {})
    assert removed == ["original"]


def test_deferred_interrupt_does_not_hide_cleanup_error():
    with pytest.raises(AgentboxError, match="cleanup failed"):
        with defer_interrupts():
            os.kill(os.getpid(), signal.SIGINT)
            raise AgentboxError("cleanup failed")


def test_deferred_interrupt_runs_after_mutation():
    finished = []
    with pytest.raises(KeyboardInterrupt):
        with defer_interrupts():
            os.kill(os.getpid(), signal.SIGINT)
            finished.append(True)
    assert finished == [True]


@pytest.fixture
def disposable_shell(temporary_control, monkeypatch):
    control, payload, removed = temporary_control
    payload["persistent"] = False
    with control.store.locked() as data:
        data["daemon_id"] = "daemon"
        data["environments"][payload["name"]] = {
            "status": "running",
            "config": payload,
            "host_addresses": [],
            "resources": {"agent": "original"},
        }
    monkeypatch.setattr("agentbox.control.local_addresses", lambda: [])
    monkeypatch.setattr(control, "owned", lambda *args: ["original"])
    return control, payload, removed


def test_disposable_shell_reserves_once_and_cleans(disposable_shell):
    control, payload, removed = disposable_shell

    def execute(*args, **kwargs):
        with control.store.locked() as data:
            assert data["environments"][payload["name"]]["shell_active"] is True
        with pytest.raises(AgentboxError, match="already claimed"):
            control.shell({"name": payload["name"]})
        assert removed == []
        return 17

    control.docker.exec_stream = execute
    assert control.shell({"name": payload["name"]}) == 17
    assert removed == ["original"]


def test_disposable_shell_queued_interrupt_after_reservation_cleans(disposable_shell, monkeypatch):
    control, payload, removed = disposable_shell
    save = control.save

    def interrupted(data):
        save(data)
        if data["environments"].get(payload["name"], {}).get("shell_active"):
            os.kill(os.getpid(), signal.SIGINT)

    monkeypatch.setattr(control, "save", interrupted)
    with pytest.raises(KeyboardInterrupt):
        control.shell({"name": payload["name"]})
    assert removed == ["original"]
    with control.store.locked() as data:
        assert payload["name"] not in data["environments"]


def test_disposable_shell_does_not_remove_replacement(disposable_shell):
    control, payload, removed = disposable_shell

    def replace(*args, **kwargs):
        with control.store.locked() as data:
            data["environments"][payload["name"]] = {"resources": {"agent": "replacement"}}
        return 0

    control.docker.exec_stream = replace
    with pytest.raises(AgentboxError, match="replacement kept"):
        control.shell({"name": payload["name"]})
    assert removed == []


def test_persistent_shell_uses_selected_agent_without_removal(disposable_shell):
    control, payload, removed = disposable_shell
    with control.store.locked() as data:
        data["environments"][payload["name"]]["config"]["persistent"] = True

    def replace(identifier, command, *args, **kwargs):
        assert identifier == "original"
        assert command == ["bash"]
        with control.store.locked() as data:
            data["environments"][payload["name"]] = {
                "resources": {"agent": "replacement"},
                "config": {"persistent": False},
            }
        return 0

    control.docker.exec_stream = replace
    assert control.shell({"name": payload["name"]}) == 0
    assert removed == []
