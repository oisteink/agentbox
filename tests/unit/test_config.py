import copy

import pytest

from agentbox.config import load, parse
from agentbox.errors import AgentboxError


@pytest.fixture
def config():
    return {
        "name": "example-dev",
        "image": "codex",
        "mounts": [{"project": "example", "target": "/home/agent/src/example"}],
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


@pytest.mark.parametrize("suffix", [".yaml", ".yml"])
def test_saved_configuration_name(monkeypatch, tmp_path, config, suffix):
    import yaml

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "settings/agentbox/environments"
    folder.mkdir(parents=True)
    (folder / f"saved{suffix}").write_text(yaml.safe_dump(config))
    assert load("saved").name == config["name"]
    assert load(f"saved{suffix}").name == config["name"]


def test_explicit_local_configuration_wins(monkeypatch, tmp_path):
    from agentbox.config import resolve_file

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "settings/agentbox/environments"
    folder.mkdir(parents=True)
    (folder / "saved.yaml").touch()
    local = tmp_path / "saved.yaml"
    local.touch()
    assert resolve_file("saved.yaml").resolve() == local
    assert resolve_file("./saved").resolve() == tmp_path / "saved"


def test_ambiguous_saved_configuration_requires_path(monkeypatch, tmp_path):
    from agentbox.config import resolve_file

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "agentbox/environments"
    folder.mkdir(parents=True)
    for suffix in (".yaml", ".yml"):
        (folder / f"saved{suffix}").touch()
    with pytest.raises(AgentboxError, match="Multiple configuration files"):
        resolve_file("saved")
    assert resolve_file("saved.yml") == folder / "saved.yml"


def test_saved_configuration_defaults_to_home(monkeypatch, tmp_path):
    from agentbox.config import resolve_file

    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".config/agentbox/environments/saved.yaml"
    path.parent.mkdir(parents=True)
    path.touch()
    # A project file must not shadow a saved short name from the trusted directory.
    (tmp_path / "saved").write_text("untrusted local file")
    assert resolve_file("saved") == path
