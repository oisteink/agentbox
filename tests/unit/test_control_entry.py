"""The service entry point must authenticate before touching control state."""

import io
import json
import os
from types import SimpleNamespace

import pytest

from agentbox import cli


@pytest.mark.parametrize("wrong_identity", ["service", "operator", "missing-sudo"])
def test_unauthorized_control_caller_cannot_dispatch(monkeypatch, capsys, wrong_identity):
    uid = os.getuid()
    settings = {"service_uid": uid, "operator_uid": uid + 1}
    monkeypatch.setattr(cli, "load_settings", lambda: settings)
    monkeypatch.setenv("SUDO_UID", str(settings["operator_uid"]))
    if wrong_identity == "service":
        settings["service_uid"] += 2
    elif wrong_identity == "operator":
        monkeypatch.setenv("SUDO_UID", str(uid + 2))
    else:
        monkeypatch.delenv("SUDO_UID")
    monkeypatch.setattr("sys.stdin", io.StringIO('{"action":"remove","name":"example"}'))
    monkeypatch.setattr(cli, "Control", lambda settings: pytest.fail("Unauthorized dispatch"))
    with pytest.raises(SystemExit) as error:
        cli.control_main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    frame = json.loads(captured.out)
    assert frame["error"]["code"] == "permission_denied"
    assert "requires the configured sudo caller and service user" in frame["error"]["message"]


@pytest.mark.parametrize("payload", ["not-json", "[]", '{"action":42}', "x" * 1048577])
def test_malformed_control_input_is_rejected_without_echo(monkeypatch, capsys, payload):
    uid = os.getuid()
    monkeypatch.setattr(cli, "load_settings", lambda: {"service_uid": uid, "operator_uid": uid})
    monkeypatch.setenv("SUDO_UID", str(uid))
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))
    monkeypatch.setattr(cli, "Control", lambda settings: pytest.fail("Malformed input dispatched"))
    with pytest.raises(SystemExit) as error:
        cli.control_main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == "" and payload not in captured.out
    assert json.loads(captured.out)["ok"] is False


def test_control_subprocess_failure_does_not_echo_request_or_output(monkeypatch, capsys):
    import subprocess

    from agentbox.control import Control

    uid = os.getuid()
    secret = "synthetic-control-credential"
    monkeypatch.setattr(cli, "load_settings", lambda: {"service_uid": uid, "operator_uid": uid})
    monkeypatch.setenv("SUDO_UID", str(uid))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"action": "start", "key": secret})))

    def fail_dispatch(self, request):
        raise subprocess.CalledProcessError(1, ["client", secret], output=secret, stderr=secret)

    # Only the external operation fails; use the actual entry point/error handler.
    monkeypatch.setattr(
        Control, "__init__", lambda self, settings: setattr(self, "docker", SimpleNamespace())
    )
    monkeypatch.setattr(Control, "dispatch", fail_dispatch)
    with pytest.raises(SystemExit) as error:
        cli.control_main()
    assert error.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out)["error"]["message"] == "CalledProcessError"
    assert secret not in captured.out
