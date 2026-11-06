"""Session ownership, shared latch, generation boundaries and failed launch cleanup."""

import copy
import fcntl
import json
import os
import signal
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from agentbox import config, sessions
from agentbox.control import Control, defer_interrupts
from agentbox.errors import AgentboxError


@pytest.fixture
def lifecycle(tmp_path, monkeypatch):
    control = Control(
        {"home": str(tmp_path), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    payload = {
        "name": "example",
        "image": "base",
        "mounts": [{"source": "data", "target": "/workspace"}],
    }
    request = {
        "action": "start",
        "config": payload,
        "recipe_digest": "a" * 64,
        "client": sessions.identity(),
    }
    scope = {"mutations": [], "ready": [], "commands": [], "confirmed": 0}

    def start(data, payload, tokens, *, session, **kwargs):
        name = payload["name"]
        entry = data["environments"].get(name)
        running = bool(entry and entry["status"] == "running")
        if not entry:
            entry = {
                "config": json.loads(json.dumps(config.parse(payload).to_dict())),
                "resources": {"agent": "agent"},
                "status": "running",
                "host_addresses": [],
            }
            data["environments"][name] = entry
        control.claim_session(entry, session, running=running)
        entry["status"] = "running"
        directory = control.store.root / "environments" / name
        directory.mkdir(parents=True, exist_ok=True)
        control.save(data)
        return entry

    def owned(data, name, kind):
        roles = ("agent", "proxy") if kind == "container" else ("inside", "outside")
        resources = data["environments"].get(name, {}).get("resources", {})
        return [resources[role] for role in roles if role in resources]

    def assert_locked():
        fd = os.open(control.store.root / "lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)

    def confirm(intent, deadline, discovered):
        assert_locked()
        saved = json.loads((control.store.root / "state.json").read_text())
        assert saved["environments"]["example"]["launches"]
        intent["exec"] = "f" * 64
        discovered()
        scope["confirmed"] += 1

    @contextmanager
    def execution(identifier, command, terminal):
        assert_locked()
        scope["commands"].append((identifier, command))

        def drain(directory):
            fd = os.open(control.store.root / "lock", os.O_RDWR)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finally:
                os.close(fd)
            return scope["drain"]() if "drain" in scope else 17

        yield SimpleNamespace(drain=drain)

    def verified(data):
        data["daemon_id"] = "daemon"

    monkeypatch.setattr(control, "verified", verified)
    monkeypatch.setattr(control, "start", start)
    monkeypatch.setattr(control, "owned", owned)
    control.docker = SimpleNamespace(
        output=None,
        ready=lambda: scope["ready"].append(True),
        execution=execution,
        launch_intent=lambda agent, deadline: {"agent": agent, "exec": None},
        confirm_launch=confirm,
        mutate=lambda *a: scope["mutations"].append(a),
    )
    return control, request, scope


def state(control):
    with control.store.locked() as data:
        return copy.deepcopy(data["environments"].get("example"))


def test_session_releases_lock_preserves_exit_and_stops_own_start(lifecycle):
    control, request, scope = lifecycle
    assert control.session(request) == 17
    assert scope["confirmed"] == 1 and scope["ready"] == [True]
    assert scope["commands"] == [("agent", ["bash"])]
    assert scope["mutations"] == [("container", "stop", "--time", "2", "agent")]
    assert state(control)["status"] == "stopped"
    assert "runtime" not in state(control)


@pytest.mark.parametrize("persistent", [False, True])
def test_keep_running_is_latched_and_stop_overrides_it(lifecycle, persistent):
    control, request, scope = lifecycle
    request["config"]["persistent"] = persistent
    request["keep_running"] = True
    control.session(request)
    first = state(control)["runtime"]["generation"]
    request["keep_running"] = False
    control.session(request)
    assert not scope["mutations"]
    assert state(control)["runtime"]["generation"] == first
    assert state(control)["runtime"]["keep_running"]
    with control.store.locked() as data:
        control.stop(data, "example")
    if persistent:
        assert state(control)["status"] == "stopped"
        assert "runtime" not in state(control)
    else:
        assert state(control) is None


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
@pytest.mark.parametrize("late_keep", [False, True])
def test_two_sessions_finish_in_either_order_and_read_latest_latch(lifecycle, order, late_keep):
    control, request, scope = lifecycle
    base = {
        "id": "first",
        "generation": "period",
        "client": sessions.identity(),
        "helper": sessions.identity(),
        "keep_running": False,
    }
    second = dict(base, id="second", generation="unused", keep_running=late_keep)
    with control.store.locked() as data:
        entry = {
            "status": "running",
            "config": {"persistent": True},
            "resources": {"agent": "agent"},
        }
        data["environments"]["example"] = entry
        control.claim_session(entry, base, running=False)
        control.claim_session(entry, second, running=True)
    chosen = [base, second]
    control.release_session("example", chosen[order[0]])
    assert not scope["mutations"]
    assert len(state(control)["runtime"]["sessions"]) == 1
    control.release_session("example", chosen[order[1]])
    assert bool(scope["mutations"]) is not late_keep
    if late_keep:
        assert state(control)["runtime"]["sessions"] == {}
        assert state(control)["runtime"]["keep_running"]


def test_old_finally_never_stops_new_period_even_with_same_agent(lifecycle):
    control, request, scope = lifecycle

    def replace():
        with control.store.locked() as data:
            entry = data["environments"]["example"]
            control.stop(data, "example")
            entry["runtime"] = {
                "generation": "new-period",
                "agent": "agent",
                "keep_running": True,
                "sessions": {},
            }
            entry["status"] = "running"
        scope["mutations"].clear()
        return 0

    scope["drain"] = replace
    assert control.session(request) == 0
    assert scope["mutations"] == [] and state(control)["runtime"]["generation"] == "new-period"


def test_existing_external_running_container_is_retained(lifecycle):
    control, request, scope = lifecycle
    with control.store.locked() as data:
        data["environments"]["example"] = {
            "status": "running",
            "resources": {"agent": "agent"},
            "config": json.loads(json.dumps(config.parse(request["config"]).to_dict())),
        }
    control.session(request)
    assert not scope["mutations"] and state(control)["runtime"]["keep_running"]


def test_nonpersistent_session_removes_resources_and_state(lifecycle):
    control, request, scope = lifecycle
    request["config"]["persistent"] = False
    assert control.session(request) == 17
    assert state(control) is None
    assert ("container", "rm", "agent") in scope["mutations"]


def test_queued_interrupt_before_launch_cleans_without_unknown_intent(lifecycle, monkeypatch):
    control, request, scope = lifecycle
    original = control.save
    sent = False

    def interrupt(data):
        nonlocal sent
        original(data)
        if data["environments"].get("example", {}).get("runtime") and not sent:
            sent = True
            os.kill(os.getpid(), signal.SIGINT)

    monkeypatch.setattr(control, "save", interrupt)
    with pytest.raises(KeyboardInterrupt):
        control.session(request)
    assert state(control)["status"] == "stopped"
    assert not state(control).get("launches") and not scope["ready"]


def test_failed_launch_preserves_quarantine_across_stop_and_rejects_restart(lifecycle):
    control, request, scope = lifecycle

    def fail(*args):
        raise AgentboxError("Inspection unavailable")

    control.docker.confirm_launch = fail
    with pytest.raises(AgentboxError) as error:
        control.session(request)
    assert error.value.code == "launch_unknown"
    assert state(control)["launches"] and not scope["ready"]
    with control.store.locked() as data:
        control.stop(data, "example")
    assert state(control)["launches"]
    with pytest.raises(AgentboxError) as error:
        control.session(request)
    assert error.value.code == "launch_unknown" and len(scope["commands"]) == 1
    with control.store.locked() as data:
        control.remove(data, "example")
    assert state(control) is None


@pytest.mark.parametrize("keep", [False, True])
def test_reaper_recognizes_dead_process_identity_and_honors_latch(lifecycle, keep):
    control, request, scope = lifecycle
    dead = dict(sessions.identity(), start=-1)
    with control.store.locked() as data:
        data["environments"]["example"] = {
            "status": "running",
            "resources": {"agent": "agent"},
            "config": {"persistent": True},
            "runtime": {
                "generation": "period",
                "agent": "agent",
                "keep_running": keep,
                "sessions": {"lost": {"client": dead, "helper": sessions.identity()}},
            },
        }
    with control.store.locked() as data:
        control.reap_sessions(data)
    assert bool(scope["mutations"]) is not keep
    if keep:
        assert state(control)["runtime"]["sessions"] == {}


def test_observation_error_does_not_reap_live_session(lifecycle, monkeypatch):
    control, request, scope = lifecycle
    request["keep_running"] = True
    original = sessions.identity

    def drain():
        def unavailable(pid=None):
            raise AgentboxError("Permission denied", code="process_observation_failed")

        monkeypatch.setattr(sessions, "identity", unavailable)
        try:
            with control.store.locked() as data:
                with pytest.raises(AgentboxError):
                    control.reap_sessions(data)
                assert len(data["environments"]["example"]["runtime"]["sessions"]) == 1
        finally:
            monkeypatch.setattr(sessions, "identity", original)
        return 0

    scope["drain"] = drain
    assert control.session(request) == 0 and not scope["mutations"]


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


def test_partial_startup_with_dead_helper_removes_networks(lifecycle):
    control, request, scope = lifecycle
    with control.store.locked() as data:
        data["environments"]["example"] = {
            "status": "creating",
            "resources": {"inside": "inside"},
            "config": {"persistent": True},
            "runtime": {
                "generation": "period",
                "agent": None,
                "keep_running": False,
                "sessions": {
                    "lost": {
                        "client": sessions.identity(),
                        "helper": dict(sessions.identity(), start=-1),
                    }
                },
            },
        }
    with control.store.locked() as data:
        control.reap_sessions(data)
    assert state(control) is None and ("network", "rm", "inside") in scope["mutations"]


def test_dead_helper_pending_launch_stops_other_sessions_but_preserves_intent(lifecycle):
    control, request, scope = lifecycle
    live = {"client": sessions.identity(), "helper": sessions.identity()}
    with control.store.locked() as data:
        data["environments"]["example"] = {
            "status": "running",
            "resources": {"agent": "agent"},
            "config": {"persistent": True},
            "runtime": {
                "generation": "period",
                "agent": "agent",
                "keep_running": True,
                "sessions": {
                    "live": live,
                    "lost": dict(live, helper=dict(sessions.identity(), start=-1)),
                },
            },
            "launches": {"lost": {"agent": "agent", "exec": None}},
        }
    with control.store.locked() as data:
        control.reap_sessions(data)
    assert state(control)["status"] == "launch-unknown"
    assert state(control)["launches"] and "runtime" not in state(control)


def test_run_name_collision_never_cleans_existing_environment(lifecycle):
    control, request, scope = lifecycle
    request["action"] = "run"
    request["config"]["persistent"] = False
    existing = {
        "status": "running",
        "resources": {"agent": "other"},
        "config": {"persistent": True},
    }
    with control.store.locked() as data:
        data["environments"]["example"] = existing
    with pytest.raises(AgentboxError) as error:
        control.session(request)
    assert error.value.code == "environment_exists"
    assert state(control) == existing and not scope["mutations"]


def test_cleanup_error_is_reported_over_command_exit(lifecycle):
    control, request, scope = lifecycle

    def fail(*args):
        raise AgentboxError("Stop cleanup failed")

    control.docker.mutate = fail
    with pytest.raises(AgentboxError, match="Stop cleanup failed"):
        control.session(request)
