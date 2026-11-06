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

    def rpc(request, **kwargs):
        requests.append(request)
        return cli.StreamResult(
            {"type": "result", "ok": True, "data": {"name": "example-codex"}, "exit_code": 0}
        )

    monkeypatch.setattr(cli, "load_settings", lambda: {"operator_uid": os.getuid()})
    monkeypatch.setattr(cli, "ensure_image", lambda environment, **kwargs: "0" * 64)
    monkeypatch.setattr(cli, "rpc", rpc)
    monkeypatch.setattr("sys.argv", ["abx", "start", str(path)])
    with pytest.raises(SystemExit) as exit:
        cli.main()
    assert exit.value.code == 0
    assert len(requests) == 1
    assert requests[0]["action"] == "start"
    assert requests[0]["config"]["name"] == "example-codex"
    assert requests[0]["config"]["mounts"][0]["source"] == "example"
    assert requests[0]["config"]["network"]["allow"] == ({"host": "api.example.com", "port": 443},)
    assert capsys.readouterr().out == ""


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
    monkeypatch.setattr(cli, "ensure_image", lambda environment, **kwargs: "0" * 64)
    monkeypatch.setattr(cli.config, "load", lambda path: parse(data))
    monkeypatch.setenv("hf_token", "wrong-client-value")
    monkeypatch.setenv("hugging_face_token", "synthetic-source")
    requests = []
    monkeypatch.setattr(
        cli,
        "rpc",
        lambda request, **kwargs: requests.append(request)
        or cli.StreamResult({"type": "result", "ok": True, "exit_code": 0}),
    )
    monkeypatch.setattr("sys.argv", ["abx", "start", str(tmp_path / "alias.yaml")])
    with pytest.raises(SystemExit) as exit:
        cli.main()
    assert exit.value.code == 0
    assert requests[0]["tokens"] == {"hugging_face_token": "synthetic-source"}
    assert "synthetic-source" not in capsys.readouterr().out


def test_exec_accepts_keep_after_config_and_keeps_tool_arguments_literal():
    args = cli.parser().parse_args(
        ["exec", "example", "--keep-running", "--", "tool", "--json", "--keep-running"]
    )
    assert args.keep_running and args.command == ["tool", "--json", "--keep-running"]
    assert cli.json_requested(["exec", "example", "--json", "--", "tool"])
    assert not cli.json_requested(["exec", "example", "--", "tool", "--json"])


def test_run_uses_distinct_names_without_altering_source(monkeypatch):
    from agentbox.config import parse
    from agentbox.output import success

    environment = parse(
        {"name": "example", "image": "base", "mounts": [{"source": "data", "target": "/workspace"}]}
    )
    requests = []
    monkeypatch.setattr(cli, "ensure_image", lambda *args, **kwargs: "a" * 64)
    monkeypatch.setattr(
        cli,
        "rpc",
        lambda request, **kwargs: requests.append(request)
        or cli.StreamResult(success(exit_code=0), input_ready=True),
    )
    cli.run_environment(environment)
    cli.run_environment(environment)
    names = [request["config"]["name"] for request in requests]
    assert names[0] != names[1] and all(name.startswith("example-run-") for name in names)
    assert all(not request["config"]["persistent"] for request in requests)
    assert environment.name == "example" and environment.persistent
