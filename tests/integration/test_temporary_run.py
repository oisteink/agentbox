import json
import shlex
import signal
import subprocess
import time

import pytest
from conftest import cli


def instances(configured):
    return {
        name: entry
        for name, entry in json.loads(cli("status").stdout).items()
        if name.startswith(configured[:31] + "-run-")
    }


@pytest.mark.parametrize("operation", ["run", "start"])
@pytest.mark.parametrize("exit_code", [0, 17])
def test_temporary_command_output_exit_and_mount_preservation(lab, exit_code, operation):
    mount, path = lab.mount()
    name, config = lab.configuration(
        mount,
        persistent=False,
        command=[
            "python3",
            "-c",
            "import sys; from pathlib import Path; "
            "assert not Path('/home/agent/dirty').exists(); "
            "Path('/home/agent/dirty').write_text('discard'); "
            "Path('/workspace/kept').write_text(sys.argv[1]); "
            "print('task-stdout', flush=True); print('task-stderr', file=sys.stderr); "
            f"sys.exit({exit_code})",
            "argument with spaces;$(touch unwanted)",
        ],
    )
    for _ in range(2):
        result = cli(operation, str(config), check=False)
        assert result.returncode == exit_code, result.stderr
        assert "task-stdout" in result.stdout and "task-stderr" in result.stderr
        assert (path / "kept").read_text() == "argument with spaces;$(touch unwanted)"
        assert not (path / "unwanted").exists()
        lab.assert_removed(name)
        assert not instances(name)
    if operation == "start":
        assert "non-persistent" in result.stderr
    else:
        assert "Temporary instance:" in result.stderr


def test_run_is_independent_of_existing_environment(lab):
    mount, path = lab.mount()
    name = lab.start(mount, command=["sh", "-c", "echo task > /workspace/result"])
    before = lab.state(name)["resources"]
    cli("exec", name, "--", "touch", "/home/agent/original")
    result = cli("run", str(lab.environments[name]))
    assert result.returncode == 0 and "Temporary instance:" in result.stderr
    assert lab.state(name)["resources"] == before
    assert not instances(name)
    assert (path / "result").read_text() == "task\n"
    cli("exec", name, "--", "test", "-e", "/home/agent/original")


def test_temporary_run_terminal_input_and_size(lab):
    mount, _ = lab.mount()
    name, config = lab.configuration(
        mount,
        command=[
            "python3",
            "-c",
            "import os; assert os.isatty(0) and os.isatty(1); "
            "print('size=%sx%s' % tuple(os.get_terminal_size(1)), flush=True); "
            "print('reply:' + input()[::-1], flush=True)",
        ],
    )
    command = shlex.join(["/usr/local/bin/abx", "run", str(config)])
    result = subprocess.run(
        ["script", "-q", "-e", "-c", "stty rows 33 cols 83; exec " + command, "/dev/null"],
        input="terminal-input\n",
        text=True,
        capture_output=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "size=83x33" in result.stdout and "reply:tupni-lanimret" in result.stdout
    lab.assert_removed(name)
    assert not instances(name)


@pytest.mark.parametrize("operation", ["run", "start"])
@pytest.mark.parametrize("terminal", [False, True])
def test_temporary_ctrl_c_cleans_up_without_blocking_other_environment(lab, terminal, operation):
    mount, path = lab.mount()
    other = lab.start(mount)
    name, config = lab.configuration(
        mount,
        persistent=False,
        command=["sh", "-c", "touch /workspace/run-ready; sleep 60"],
    )
    arguments = ["/usr/local/bin/abx", operation, str(config)]
    if terminal:
        arguments = ["script", "-q", "-e", "-c", shlex.join(arguments), "/dev/null"]
    process = subprocess.Popen(
        arguments,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    current = name
    try:
        for _ in range(200):
            if (path / "run-ready").exists():
                break
            assert process.poll() is None
            time.sleep(0.1)
        else:
            pytest.fail("Temporary command did not start")
        if operation == "run":
            active = instances(name)
            assert len(active) == 1
            current = next(iter(active))
        state = lab.state(current)
        assert len(state["runtime"]["sessions"]) == 1
        assert not state["runtime"]["keep_running"]
        cli("exec", other, "--", "true", timeout=5)
        if terminal:
            process.stdin.write("\x03")
            process.stdin.flush()
        else:
            process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 130, stdout + stderr
        assert "Traceback" not in stdout + stderr
        lab.assert_removed(current)
        assert not instances(name)
        cli("exec", other, "--", "true")
    finally:
        if process.poll() is None:
            cli("remove", current, check=False)
            process.terminate()
            process.wait(timeout=10)


def test_stop_removes_nonpersistent_environment(lab):
    mount, path = lab.mount()
    name = lab.start(mount, persistent=False)
    cli("exec", name, "--", "sh", "-c", "touch /home/agent/dirty /workspace/kept")
    assert json.loads(cli("stop", name).stdout)["status"] == "removed"
    lab.assert_removed(name)
    assert (path / "kept").exists()
