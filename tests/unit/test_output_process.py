"""Public JSON and real duplex processes, independent of Docker and sudo."""

import io
import json
import os
import subprocess
import sys

import pytest

from agentbox import cli
from agentbox.errors import AgentboxError
from agentbox.output import Output, confirm, success
from agentbox.process import pump


def test_duplex_large_input_separate_output_utf8_and_early_exit(tmp_path):
    for program in (
        "import os,sys; os.write(1,b'x'*200000); "
        "data=sys.stdin.buffer.read(); os.write(2,data); "
        "os.write(1,b'\\xe2'); os.write(1,b'\\x82\\xac\\xff'); sys.exit(17)",
        "import sys; print('early'); sys.exit(17)",
    ):
        source = tmp_path / "input"
        source.write_bytes(b"y" * 200000)
        received = {"stdout": "", "stderr": ""}
        child = subprocess.Popen(
            [sys.executable, "-c", program],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        with source.open("rb") as stream:
            code = pump(
                child,
                lambda name, text: received.__setitem__(name, received[name] + text),
                source=stream,
            )
        assert code == 17
        if "early" in received["stdout"]:
            assert received["stderr"] == ""
        else:
            assert received == {"stdout": "x" * 200000 + "€�", "stderr": "y" * 200000}


def test_interrupt_while_waiting_for_input_has_no_input_thread(tmp_path):
    # The child interrupts its waiting parent; the input pipe deliberately stays open.
    child = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "import os,signal,time; time.sleep(.1); os.kill(os.getppid(), signal.SIGINT); time.sleep(30)",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=0,
    )
    read, write = os.pipe()
    try:
        with os.fdopen(read, "rb") as source:
            assert pump(child, lambda *_: None, source=source) == 130
    finally:
        os.close(write)
        if child.poll() is None:
            child.kill()
            child.wait()


@pytest.mark.parametrize(
    "arguments",
    [
        ["--json", "unknown-secret"],
        ["validate", "--json"],
        ["--json", "image", "new", "example", "--template", "secret-value"],
        ["--json", "--help"],
        ["image", "--json", "build", "--help"],
    ],
)
def test_public_json_parse_and_help(arguments):
    result = subprocess.run(
        [sys.executable, "-c", "from agentbox.cli import main; main()", *arguments],
        capture_output=True,
        text=True,
        env=os.environ | {"PYTHONPATH": "src"},
    )
    assert result.returncode == 0 and not result.stderr
    frame = json.loads(result.stdout)
    assert frame["type"] == "result"
    assert "unknown-secret" not in result.stdout and "secret-value" not in result.stdout
    if "--help" in arguments:
        assert frame["ok"] and "usage:" in frame["data"]["help"]
    else:
        assert frame["error"]["code"] == "invalid_arguments"


def test_exec_flags_belong_to_child():
    assert not cli.json_requested(["exec", "environment", "--", "tool", "--json"])
    assert cli.json_requested(["exec", "--json", "environment", "--", "tool"])
    args = cli.parser().parse_args(["exec", "environment", "--", "tool", "--json"])
    assert args.command == ["tool", "--json"]


def test_confirmation_does_not_prompt_in_json(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO())
    with pytest.raises(AgentboxError) as error:
        confirm("Stop environments?", ["example"], json_mode=True)
    assert error.value.code == "confirmation_required"
    assert error.value.details == {"affected": ["example"]}
    confirm("Stop environments?", ["example"], json_mode=True, yes=True)


def test_command_failure_is_in_json_not_cli_status(capsys):
    assert Output(True).finish(success(exit_code=17)) == 0
    frame = json.loads(capsys.readouterr().out)
    assert not frame["ok"] and frame["exit_code"] == 17


@pytest.mark.parametrize(
    "payload",
    [
        "",
        '{"type":"output","stream":"stdout","data":"partial"}\n',
        "raw diagnostic\n",
        '{"type":"result","ok":true}\n{"type":"result","ok":true}\n',
    ],
)
def test_control_protocol_requires_one_final_result(monkeypatch, payload):
    popen = subprocess.Popen

    def child(*args, **kwargs):
        return popen(
            [sys.executable, "-c", f"import sys; sys.stdin.read(); sys.stdout.write({payload!r})"],
            **kwargs,
        )

    monkeypatch.setattr(cli.subprocess, "Popen", child)
    monkeypatch.setattr(cli, "_output", Output(True))
    with pytest.raises(AgentboxError) as error:
        cli.rpc({"action": "status"})
    assert error.value.code == "control_protocol_error"
