"""Preparation races and validation before any stopped layer is discarded."""

import ipaddress
import json
import os
from types import SimpleNamespace

import pytest

from agentbox import config
from agentbox.control import Control
from agentbox.errors import AgentboxError

DIGEST = "a" * 64


@pytest.fixture
def prepared(tmp_path, monkeypatch):
    control = Control(
        {"home": str(tmp_path), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    payload = {
        "name": "example",
        "image": "recipe",
        "mounts": [{"source": "data", "target": "/workspace"}],
    }
    environment = config.parse(payload)
    entry = {
        "config": json.loads(json.dumps(environment.to_dict())),
        "resources": {"agent": "agent"},
        "host_addresses": ["10.0.2.15"],
        "placeholders": {},
        "status": "running",
    }
    data = {"schema": 2, "installation": "test", "mounts": {}, "environments": {"example": entry}}
    current = {
        "Id": "sha256:current",
        "Architecture": "amd64",
        "Config": {
            "Labels": {
                "agentbox.installation": "test",
                "agentbox.image": "recipe",
                "agentbox.recipe-digest": DIGEST,
            }
        },
    }
    actual = {"Image": "sha256:current", "State": {"Running": True}}
    mutations = []

    def inspect(kind, identifier):
        return current if kind == "image" else actual

    monkeypatch.setattr(
        control.docker, "run", lambda *a, **k: SimpleNamespace(stdout=current["Id"])
    )
    monkeypatch.setattr(control.docker, "inspect", inspect)
    monkeypatch.setattr(control.docker, "mutate", lambda *a, **k: mutations.append(a))
    monkeypatch.setattr(control, "owned", lambda *a: ["agent"])
    monkeypatch.setattr(control, "check_guard", lambda: None)
    monkeypatch.setattr(control, "check_mounts", lambda *a: [])
    monkeypatch.setattr(
        control,
        "subnets",
        lambda: [ipaddress.ip_network("172.28.0.0/28"), ipaddress.ip_network("172.28.0.16/28")],
    )
    monkeypatch.setattr(control, "verified", lambda *a: {})
    monkeypatch.setattr("agentbox.control.local_addresses", lambda: ["10.0.2.15"])
    monkeypatch.setattr(control, "remove", lambda *a: pytest.fail("Stopped layer must be retained"))
    monkeypatch.setattr(
        control, "apply_proxy", lambda *a: pytest.fail("Proxy must remain unchanged")
    )
    return control, data, payload, current, actual, mutations


def test_pending_keeps_agent_and_absent_proxy(prepared):
    control, data, payload, _, _, mutations = prepared
    payload["resources"] = {"pids": 128}
    result = control.start(data, payload, recipe_digest="b" * 64)
    assert result["pending_changes"] and not result["proxy_active"]
    assert data["environments"]["example"]["resources"] == {"agent": "agent"}
    assert not mutations


def test_exec_preparation_never_reopens_proxy_on_running_agent(prepared):
    control, data, payload, _, _, mutations = prepared
    result = control.start(data, payload, recipe_digest=DIGEST)
    assert not result["pending_changes"] and not result["proxy_active"] and not mutations


def test_stopped_start_rechecks_digest_under_control_lock(prepared):
    control, data, payload, _, actual, mutations = prepared
    actual["State"]["Running"] = False
    with pytest.raises(AgentboxError) as error:
        control.start(data, payload, recipe_digest="b" * 64)
    assert error.value.code == "image_outdated" and not mutations


def test_address_guard_stops_before_pending_return(prepared):
    control, data, payload, _, _, mutations = prepared
    data["environments"]["example"]["host_addresses"] = ["old-address"]
    with pytest.raises(AgentboxError) as error:
        control.start(data, payload, recipe_digest="b" * 64)
    assert error.value.code == "image_outdated"
    assert mutations[0][:2] == ("container", "stop")
    assert data["environments"]["example"]["status"] == "stopped-host-address-change"


@pytest.mark.parametrize("invalid", ["profile", "mount", "token", "dns"])
def test_invalid_new_profile_is_rejected_before_layer_removal(prepared, monkeypatch, invalid):
    control, data, payload, current, actual, mutations = prepared
    actual["State"]["Running"] = False
    actual["Image"] = "sha256:old"
    tokens = {}
    if invalid == "profile":
        current["Config"]["Volumes"] = {"/data": {}}
    elif invalid == "mount":

        def unavailable(*args):
            raise AgentboxError("Mount is revoked")

        monkeypatch.setattr(control, "check_mounts", unavailable)
    elif invalid == "token":
        payload["network"] = {"allow": [{"host": "api.example.com", "port": 443}]}
        payload["credentials"] = [
            {"host": "api.example.com", "port": 443, "header": "Authorization", "env": "TOKEN"}
        ]
        tokens = {"TOKEN": "invalid\\nvalue".replace("\\n", "\n")}
    else:

        def denied(*args):
            raise AgentboxError("DNS resolved to private address")

        monkeypatch.setattr("agentbox.control.policy.resolve", denied)
    with pytest.raises(AgentboxError):
        control.start(data, payload, tokens, recipe_digest=DIGEST)
    assert not mutations
    assert data["environments"]["example"]["resources"]["agent"] == "agent"


def test_stopped_nonpersistent_layer_is_never_reused_after_incomplete_cleanup(
    prepared, monkeypatch
):
    control, data, payload, _, actual, mutations = prepared
    payload["persistent"] = False
    data["environments"]["example"]["config"]["persistent"] = False
    actual["State"]["Running"] = False

    def replacing(*args, **kwargs):
        raise AgentboxError("Validated replacement required")

    monkeypatch.setattr(control, "remove", replacing)
    with pytest.raises(AgentboxError, match="Validated replacement required"):
        control.start(data, payload, recipe_digest=DIGEST)
    assert not mutations
