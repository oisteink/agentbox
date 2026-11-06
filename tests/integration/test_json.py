"""Exercise the installed public machine interface through sudo and rootless Docker."""

import json
import os
import signal
import subprocess

from conftest import cli, machine


def test_installed_metadata_parser_and_human_table(lab):
    mount, _ = lab.mount()
    name = lab.start(mount)
    assert "NAME" in subprocess.check_output(["abx", "status"], text=True)
    assert machine("status")[-1]["data"][name]["status"] == "running"
    assert machine("unknown-secret")[-1]["error"]["code"] == "invalid_arguments"
    assert not machine("exec", name, "--", "false")[-1]["ok"]
    assert machine("exec", name, "--", "false")[-1]["exit_code"] == 1
    assert "usage:" in machine("--help")[-1]["data"]["help"]
    assert (
        machine("validate", "/missing/example.yaml")[-1]["error"]["code"] == "invalid_configuration"
    )


def test_installed_duplex_json_and_private_logs(lab):
    mount, _ = lab.mount()
    name = lab.start(mount)
    program = (
        "import os,sys; assert not os.isatty(0); assert not os.isatty(1); "
        "os.write(1,b'x'*200000); data=sys.stdin.buffer.read(); os.write(2,data); "
        "os.write(1,b'\\xe2'); os.write(1,b'\\x82\\xac\\xff'); sys.exit(17)"
    )
    frames = machine("exec", name, "--", "python3", "-c", program, input="y" * 200000)
    stdout = "".join(f["data"] for f in frames[:-1] if f["stream"] == "stdout")
    stderr = "".join(f["data"] for f in frames[:-1] if f["stream"] == "stderr")
    assert stdout == "x" * 200000 + "€�" and stderr == "y" * 200000
    assert frames[-1]["exit_code"] == 17 and not frames[-1]["ok"]
    early = machine("exec", name, "--", "true", input="unread" * 100000)
    assert early[-1]["ok"]
    assert machine("logs", name)[-1]["exit_code"] == 0
    assert "y" * 100 in cli("logs", name).stdout


def test_installed_json_interrupt_cleans_temporary_environment(lab):
    mount, _ = lab.mount()
    name, config = lab.configuration(mount, command=["sh", "-c", "echo ready; cat"])
    # Keep stdin open while SIGINT passes through the actual sudo chain.
    with subprocess.Popen(
        ["/usr/local/bin/abx", "--json", "run", str(config)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    ) as process:
        first = json.loads(process.stdout.readline())
        assert first["type"] == "output" and "ready" in first["data"]
        process.send_signal(signal.SIGINT)
        process.wait(timeout=30)
        output = process.stdout.read()
        assert process.returncode == 0 and process.stderr.read() == ""
        final = json.loads(output.splitlines()[-1])
        assert not final["ok"] and final["exit_code"] == 130
    lab.assert_removed(name)


def test_installed_json_editor_forwards_input_and_status(lab):
    name, _ = lab.image()
    editor = lab.root / "editor"
    editor.write_text("#!/bin/sh\ncat\nprintf 'editor-stderr' >&2\nexit 19\n")
    editor.chmod(0o700)
    frames = machine(
        "image", "edit", name, input="editor-input", env=os.environ | {"VISUAL": str(editor)}
    )
    assert "".join(f["data"] for f in frames[:-1] if f["stream"] == "stdout") == "editor-input"
    assert "".join(f["data"] for f in frames[:-1] if f["stream"] == "stderr") == "editor-stderr"
    assert not frames[-1]["ok"] and frames[-1]["exit_code"] == 19
