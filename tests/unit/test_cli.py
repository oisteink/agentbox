import os

import pytest

from agentbox import cli


def test_start_reads_environment_name_from_file(monkeypatch, tmp_path, capsys):
    path = tmp_path / "arbitrary filename.yaml"
    path.write_text(
        "name: pubnix-codex\nimage: agentbox-dev:local\n"
        "mounts:\n  - project: pubnix\n    target: /workspace\n"
        "network:\n  allow:\n    - host: api.example.com\n      port: 443\n"
    )
    requests = []

    def rpc(request):
        requests.append(request)
        return {"status": "running"}

    monkeypatch.setattr(cli, "load_settings", lambda: {"operator_uid": os.getuid()})
    monkeypatch.setattr(cli, "rpc", rpc)
    monkeypatch.setattr("sys.argv", ["agentbox", "start", str(path)])
    cli.main()
    assert len(requests) == 1
    assert requests[0]["action"] == "start"
    assert requests[0]["config"]["name"] == "pubnix-codex"
    assert requests[0]["config"]["mounts"][0]["project"] == "pubnix"
    assert requests[0]["config"]["network"]["allow"] == ({"host": "api.example.com", "port": 443},)
    assert "running" in capsys.readouterr().out


def test_start_missing_file_does_not_contact_control(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(cli, "load_settings", lambda: {"operator_uid": os.getuid()})
    monkeypatch.setattr("sys.argv", ["agentbox", "start", str(tmp_path / "missing.yaml")])
    monkeypatch.setattr(cli, "rpc", lambda request: pytest.fail("Control must not be called"))
    with pytest.raises(SystemExit) as error:
        cli.main()
    assert error.value.code == 2
    assert capsys.readouterr().err
