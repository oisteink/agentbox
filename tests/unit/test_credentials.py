import os
from types import SimpleNamespace

import pytest

from agentbox.control import Control
from agentbox.errors import AgentboxError


def test_credential_setup_never_replays_client_error_output(tmp_path, monkeypatch):
    control = Control(
        {"home": str(tmp_path), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    with control.store.locked() as state:
        state["environments"]["test-env"] = {
            "status": "running",
            "host_addresses": [],
            "resources": {"agent": "container-id"},
        }
    monkeypatch.setattr(control, "verified", lambda data: {})
    monkeypatch.setattr(control, "owned", lambda *args: ["container-id"])
    monkeypatch.setattr("agentbox.control.local_addresses", lambda: [])
    seen = {}

    def fake_client(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            returncode=1, stdout="echoed-sensitive-value", stderr="echoed-sensitive-value"
        )

    monkeypatch.setattr(control.docker, "run", fake_client)
    with pytest.raises(AgentboxError) as failure:
        control.dispatch(
            {"action": "login-api-key", "name": "test-env", "key": "test-only-credential"}
        )
    assert "echoed-sensitive-value" not in str(failure.value)
    assert seen["source"] == "test-only-credential\n"
    assert seen["check"] is False


def test_revocation_requires_loss_of_traversal_not_just_write_permission(tmp_path, monkeypatch):
    control = Control(
        {"home": str(tmp_path), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    state = {
        "mounts": {
            "test": {
                "type": "directory",
                "path": str(tmp_path),
                "status": "revoked",
                "registration": "test",
            }
        }
    }
    monkeypatch.setattr(control, "require_idle", lambda *args: None)
    monkeypatch.setattr("agentbox.control.os.access", lambda path, mode: mode == os.X_OK)
    with pytest.raises(AgentboxError, match="still accessible"):
        control.mount(state, "revoked", {"name": "test"})
