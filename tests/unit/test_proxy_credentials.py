import json
import os
from types import SimpleNamespace

import pytest

from agentbox.config import parse
from agentbox.control import Control
from agentbox.errors import AgentboxError
from agentbox.policy import placeholders, render, token_environment, validate_placeholders


def environment():
    return {
        "name": "test-env",
        "image": "codex",
        "mounts": [{"source": "test", "target": "/workspace"}],
        "network": {"allow": [{"host": "api.example.com", "port": 443}]},
        "credentials": [
            {"host": "api.example.com", "port": 443, "header": "Authorization", "env": "MY_TOKEN"}
        ],
    }


@pytest.mark.parametrize(
    "change",
    [
        {"header": "Host"},
        {"env": "../key"},
        {"port": 80},
        {"host": "other.example.com"},
        {"secret": "plaintext"},
    ],
)
def test_invalid_credential_contract(change):
    data = environment()
    data["credentials"][0].update(change)
    with pytest.raises(AgentboxError):
        parse(data)


def test_duplicate_rules_and_casing_are_rejected():
    data = environment()
    data["credentials"].append(data["credentials"][0] | {"header": "AUTHORIZATION"})
    with pytest.raises(AgentboxError):
        parse(data)


@pytest.mark.parametrize(
    "values",
    [
        {"MY_TOKEN": "token\n"},
        {"MY_TOKEN": "x", "EXTRA": "x"},
        {"MY_TOKEN": 42},
    ],
)
def test_token_rpc_is_strict(values):
    with pytest.raises(AgentboxError):
        token_environment(parse(environment()), values)


def test_policy_and_normalized_config_contain_only_references():
    env = parse(environment())
    secret = "unique-synthetic-token"
    assert token_environment(env, {"MY_TOKEN": secret}) == {"AGENTBOX_TOKEN_0": secret}
    mapping = placeholders(env, {c.source_env: "synthetic" for c in env.credentials})
    serialized, _, _ = render(
        env.allow,
        {"api.example.com": "93.184.216.34"},
        "172.30.240.2",
        [],
        env.credentials,
        mapping,
    )
    assert secret not in serialized + json.dumps(env.to_dict())
    assert json.loads(serialized)["destinations"][0]["credentials"] == [
        {"env": "AGENTBOX_TOKEN_0", "header": "authorization", "placeholder": mapping["MY_TOKEN"]}
    ]


def test_failed_apply_removes_old_proxy_before_validating_token(tmp_path, monkeypatch):
    control = Control(
        {"home": str(tmp_path), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    env = parse(environment())
    state = {
        "environments": {
            env.name: {
                "proxy_format": 2,
                "placeholders": placeholders(
                    env, {c.source_env: "synthetic" for c in env.credentials}
                ),
                "config": json.loads(json.dumps(env.to_dict())),
                "status": "running",
                "host_addresses": [],
                "resources": {"inside": "in", "outside": "out", "proxy": "old"},
            }
        }
    }
    monkeypatch.setattr(control, "check_guard", lambda: None)
    monkeypatch.setattr(control, "check_mounts", lambda *args: [])
    monkeypatch.setattr(control, "owned", lambda *args: ["in", "out"])
    monkeypatch.setattr("agentbox.control.local_addresses", lambda: [])
    dropped = []
    monkeypatch.setattr(control, "drop_proxy", lambda *args: dropped.append("old"))
    with pytest.raises(AgentboxError, match="availability changed"):
        control.apply_proxy(state, env, {})
    assert dropped


def test_docker_credentials_never_appear_in_argv_or_errors(monkeypatch):
    from agentbox.runtime import Docker

    captured = {}

    def run(args, **kwargs):
        captured.update(args=args, **kwargs)
        return SimpleNamespace(returncode=1, stderr="echoed-sensitive-value")

    monkeypatch.setattr("agentbox.runtime.subprocess.run", run)
    with pytest.raises(AgentboxError) as failure:
        Docker(1001, "/var/lib/agentbox").run(
            "container",
            "create",
            "--env",
            "AGENTBOX_TOKEN_0",
            extra_env={"AGENTBOX_TOKEN_0": "echoed-sensitive-value"},
        )
    assert "echoed-sensitive-value" not in str(failure.value)
    assert "echoed-sensitive-value" not in captured["args"]
    assert captured["env"]["AGENTBOX_TOKEN_0"] == "echoed-sensitive-value"


def test_placeholders_are_unique_scoped_and_reusable():
    data = environment()
    data["network"]["allow"].append({"host": "other.example.com", "port": 443})
    data["credentials"].append(data["credentials"][0] | {"host": "other.example.com"})
    env = parse(data)
    mapping = placeholders(env, {c.source_env: "synthetic" for c in env.credentials})
    assert set(mapping) == {"MY_TOKEN"}
    assert mapping != placeholders(env, {c.source_env: "synthetic" for c in env.credentials})
    validate_placeholders(env, mapping)
    result, _, _ = render(
        env.allow,
        {r.host: "93.184.216.34" for r in env.allow},
        "172.30.240.2",
        [],
        env.credentials,
        mapping,
    )
    policy = json.loads(result)
    assert policy["version"] == 3
    assert {d["credentials"][0]["placeholder"] for d in policy["destinations"]} == {
        mapping["MY_TOKEN"]
    }
    data["credentials"][1]["env"] = "SECOND_TOKEN"
    with pytest.raises(AgentboxError, match="recreate"):
        validate_placeholders(parse(data), mapping)


@pytest.mark.parametrize(
    "variable",
    [
        "PATH",
        "HOME",
        "https_proxy",
        "SSL_CERT_FILE",
        "NODE_OPTIONS",
        "LD_PRELOAD",
        "GIT_CONFIG_COUNT",
        "AGENTBOX_TOKEN_0",
    ],
)
def test_token_names_cannot_override_runtime(variable):
    data = environment()
    data["credentials"][0]["env"] = variable
    with pytest.raises(AgentboxError):
        parse(data)


@pytest.mark.parametrize("variable", ["APITOKEN", "CONTEXT7_TOKEN", "CONTEXT7_API_KEY"])
def test_normal_token_names_are_supported(variable):
    data = environment()
    data["credentials"][0]["env"] = variable
    assert variable in placeholders(parse(data), {variable: "synthetic"})


@pytest.mark.parametrize(
    "mapping",
    [
        None,
        {},
        {"MY_TOKEN": "arbitrary"},
        {"MY_TOKEN": "abx-" + "a" * 64, "SECOND": "abx-" + "a" * 64},
    ],
)
def test_missing_or_ambiguous_placeholder_maps_are_rejected(mapping):
    with pytest.raises(AgentboxError):
        validate_placeholders(parse(environment()), mapping)


def test_new_variable_apply_requires_explicit_recreation_before_proxy_change(tmp_path, monkeypatch):
    control = Control(
        {"home": str(tmp_path), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    old = parse(environment())
    modified = environment()
    modified["credentials"][0]["env"] = "NEW_TOKEN"
    env = parse(modified)
    state = {
        "environments": {
            env.name: {
                "proxy_format": 2,
                "placeholders": placeholders(old, {"MY_TOKEN": "synthetic"}),
                "config": json.loads(json.dumps(old.to_dict())),
                "host_addresses": [],
                "status": "running",
            }
        }
    }
    monkeypatch.setattr(control, "check_guard", lambda: None)
    monkeypatch.setattr("agentbox.control.local_addresses", lambda: [])

    def fail_if_called(*args):
        pytest.fail("immutable agent environment must be checked before proxy changes")

    monkeypatch.setattr(control, "drop_proxy", fail_if_called)
    with pytest.raises(AgentboxError, match="recreate") as failure:
        control.apply_proxy(state, env, {"NEW_TOKEN": "synthetic"})
    assert "proxy stop test-env" in str(failure.value)
    assert "not changed" in str(failure.value)


@pytest.mark.parametrize(
    "reference", ["hf_token=hugging_face_token", " hf_token = hugging_face_token "]
)
def test_alias_lookup_and_policy_use_client_sort_order(reference):
    data = environment()
    data["credentials"][0]["env"] = reference
    data["credentials"].extend(
        [
            data["credentials"][0] | {"header": "X-API-Key", "env": "a_client=z_source"},
            data["credentials"][0] | {"header": "CONTEXT7_API_KEY", "env": "z_client=z_source"},
        ]
    )
    env = parse(data)
    rule = env.credentials[0]
    assert (rule.client_env, rule.source_env, rule.env) == (
        "hf_token",
        "hugging_face_token",
        "hf_token=hugging_face_token",
    )
    values = {"hugging_face_token": "hf-secret", "z_source": "shared-secret"}
    assert token_environment(env, values) == {
        "AGENTBOX_TOKEN_0": "shared-secret",
        "AGENTBOX_TOKEN_1": "hf-secret",
        "AGENTBOX_TOKEN_2": "shared-secret",
    }
    mapping = placeholders(env, values)
    assert set(mapping) == {"hf_token", "a_client", "z_client"}
    assert len(set(mapping.values())) == 3
    validate_placeholders(env, mapping)
    serialized, _, _ = render(
        env.allow,
        {"api.example.com": "93.184.216.34"},
        "172.30.240.2",
        [],
        env.credentials,
        mapping,
    )
    credentials = json.loads(serialized)["destinations"][0]["credentials"]
    assert credentials[0] == {
        "header": "authorization",
        "env": "AGENTBOX_TOKEN_1",
        "placeholder": mapping["hf_token"],
    }
    assert "hf-secret" not in serialized and "shared-secret" not in serialized


@pytest.mark.parametrize(
    "reference",
    ["=SOURCE", "CLIENT=", "A=B=C", "A B", "A=../key", "HOME=SOURCE", "https_proxy=SOURCE"],
)
def test_invalid_aliases_are_rejected(reference):
    data = environment()
    data["credentials"][0]["env"] = reference
    with pytest.raises(AgentboxError):
        parse(data)


def test_short_form_is_canonical_and_reserved_source_is_allowed():
    data = environment()
    data["credentials"][0]["env"] = " MY_TOKEN = MY_TOKEN "
    assert parse(data).credentials[0].env == "MY_TOKEN"
    data["credentials"][0]["env"] = "MY_TOKEN=HOME"
    assert parse(data).credentials[0].source_env == "HOME"


def test_one_client_cannot_have_conflicting_sources():
    data = environment()
    data["credentials"].append(
        data["credentials"][0] | {"header": "X-API-Key", "env": "MY_TOKEN=OTHER"}
    )
    with pytest.raises(AgentboxError, match="one host source"):
        parse(data)


@pytest.mark.parametrize("values", [{}, {"MY_TOKEN": ""}])
def test_missing_and_empty_sources_give_empty_client_environment(values):
    env = parse(environment())
    assert placeholders(env, values) == {"MY_TOKEN": ""}
    assert token_environment(env, values) == {}
    validate_placeholders(env, {"MY_TOKEN": "", "OTHER_CLIENT": ""})


@pytest.mark.parametrize("original_value,new_value", [("synthetic", ""), ("", "synthetic")])
def test_availability_transition_drops_proxy_before_recreation_error(
    tmp_path, monkeypatch, original_value, new_value
):
    env = parse(environment())
    control = Control(
        {"home": str(tmp_path), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    state = {
        "environments": {
            env.name: {
                "proxy_format": 2,
                "placeholders": placeholders(env, {"MY_TOKEN": original_value}),
                "config": json.loads(json.dumps(env.to_dict())),
                "host_addresses": [],
                "status": "running",
                "resources": {"inside": "in", "outside": "out", "proxy": "old"},
            }
        }
    }
    monkeypatch.setattr(control, "check_guard", lambda: None)
    monkeypatch.setattr(control, "check_mounts", lambda *args: [])
    monkeypatch.setattr(control, "owned", lambda *args: ["in", "out"])
    monkeypatch.setattr("agentbox.control.local_addresses", lambda: [])
    dropped = []
    monkeypatch.setattr(control, "drop_proxy", lambda *args: dropped.append("old"))
    with pytest.raises(AgentboxError, match="availability changed"):
        control.apply_proxy(state, env, {"MY_TOKEN": new_value})
    assert dropped
