import copy

import pytest

from agentbox.config import load, parse
from agentbox.errors import AgentboxError


@pytest.fixture
def config():
    return {
        "name": "pacman-dev",
        "image": "agentbox-dev:local",
        "mounts": [{"project": "pacman", "target": "/home/agent/src/pacman"}],
        "network": {"allow": [{"host": "api.example.com", "port": 443}]},
    }


def test_defaults_are_closed(config):
    config.pop("network")
    result = parse(config)
    assert result.allow == ()
    assert result.command == ("bash",)
    assert result.resources.pids == 512


@pytest.mark.parametrize(
    "key,value",
    [
        ("privileged", True),
        ("image", "--privileged"),
        ("name", "../escape"),
        ("command", "bash -c bad"),
        ("resources", {"cpus": True}),
        ("resources", {"cpus": float("nan")}),
        ("resources", {"pids": -1}),
        ("resources", {"memory": "-1g"}),
        ("workdir", "/etc"),
    ],
)
def test_rejects_unsafe_configuration(config, key, value):
    config[key] = value
    with pytest.raises(AgentboxError):
        parse(config)


@pytest.mark.parametrize("target", ["/", "/etc", "/dev/log", "/home/agent", "/a/../etc", "/a,b"])
def test_rejects_mount_targets(config, target):
    config["mounts"][0]["target"] = target
    with pytest.raises(AgentboxError):
        parse(config)


def test_rejects_nested_mount(config):
    nested = copy.deepcopy(config["mounts"][0])
    nested["target"] += "/nested"
    config["mounts"].append(nested)
    with pytest.raises(AgentboxError):
        parse(config)


@pytest.mark.parametrize(
    "host,port",
    [
        ("*.example.com", 443),
        ("127.0.0.1", 443),
        ("api.example.com", True),
        ("api.example.com", 22),
    ],
)
def test_rejects_network_expansion(config, host, port):
    config["network"]["allow"] = [{"host": host, "port": port}]
    with pytest.raises(AgentboxError):
        parse(config)


def test_duplicate_yaml_key_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("name: original\nname: replacement\n")
    with pytest.raises(AgentboxError, match="unique"):
        load(path)


def test_yaml_object_constructor_rejected(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("!!python/object/apply:os.system ['false']")
    with pytest.raises(AgentboxError):
        load(path)
