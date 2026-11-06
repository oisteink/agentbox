import os

import pytest

from agentbox import cli


def test_start_reads_environment_name_from_file(monkeypatch, tmp_path, capsys):
    path = tmp_path / "arbitrary filename.yaml"
    path.write_text(
        "name: example-codex\nimage: codex\n"
        "mounts:\n  - source: example\n    target: /workspace\n"
        "network:\n  allow:\n    - host: api.example.com\n      port: 443\n"
    )
    requests = []

    def rpc(request):
        requests.append(request)
        return {"status": "running"}

    monkeypatch.setattr(cli, "load_settings", lambda: {"operator_uid": os.getuid()})
    monkeypatch.setattr(cli, "ensure_image", lambda environment: "0" * 64)
    monkeypatch.setattr(cli, "rpc", rpc)
    monkeypatch.setattr("sys.argv", ["abx", "start", str(path)])
    cli.main()
    assert len(requests) == 1
    assert requests[0]["action"] == "start"
    assert requests[0]["config"]["name"] == "example-codex"
    assert requests[0]["config"]["mounts"][0]["source"] == "example"
    assert requests[0]["config"]["network"]["allow"] == ({"host": "api.example.com", "port": 443},)
    assert "running" in capsys.readouterr().out


def test_start_missing_file_does_not_contact_control(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: {"operator_uid": os.getuid()})
    monkeypatch.setattr("sys.argv", ["abx", "start", str(tmp_path / "missing.yaml")])
    monkeypatch.setattr(cli, "rpc", lambda request: pytest.fail("Control must not be called"))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert capsys.readouterr().err.startswith("abx: ")


def test_alias_only_reads_host_source(monkeypatch, tmp_path, capsys):
    from agentbox.config import parse

    data = {
        "name": "alias-test",
        "image": "codex",
        "mounts": [{"source": "test", "target": "/workspace"}],
        "network": {"allow": [{"host": "api.example.com", "port": 443}]},
        "credentials": [
            {
                "host": "api.example.com",
                "port": 443,
                "header": "Authorization",
                "env": "hf_token=hugging_face_token",
            }
        ],
    }
    monkeypatch.setattr(cli, "load_settings", lambda: {"operator_uid": os.getuid()})
    monkeypatch.setattr(cli, "ensure_image", lambda environment: "0" * 64)
    monkeypatch.setattr(cli.config, "load", lambda path: parse(data))
    monkeypatch.setenv("hf_token", "wrong-client-value")
    monkeypatch.setenv("hugging_face_token", "synthetic-source")
    requests = []
    monkeypatch.setattr(
        cli, "rpc", lambda request: requests.append(request) or {"status": "running"}
    )
    monkeypatch.setattr("sys.argv", ["abx", "start", str(tmp_path / "alias.yaml")])
    cli.main()
    assert requests[0]["tokens"] == {"hugging_face_token": "synthetic-source"}
    assert "synthetic-source" not in capsys.readouterr().out
