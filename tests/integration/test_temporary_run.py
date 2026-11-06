import json
import shlex
import signal
import subprocess
import time

import pytest
from conftest import cli


@pytest.mark.parametrize("operation", ["run", "shell"])
@pytest.mark.parametrize("exit_code", [0, 17])
def test_temporary_command_output_exit_and_project_preservation(lab, exit_code, operation):
    project, path = lab.project()
    name, config = lab.configuration(
        project,
        persistent=operation != "shell",
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
    original = None
    if operation == "shell":
        started = cli("start", str(config))
        assert "Non-persistent" in started.stderr
        original = lab.state(name)["resources"]["agent"]
    result = cli(operation, name if operation == "shell" else str(config), check=False)
    assert result.returncode == exit_code, result.stderr
    assert "task-stdout" in result.stdout and "task-stderr" in result.stdout
    assert (path / "kept").read_text() == "argument with spaces;$(touch unwanted)"
    assert not (path / "unwanted").exists()
    lab.assert_removed(name)
    if operation == "shell":
        assert "Non-persistent" in result.stderr
        cli("start", str(config))
        assert lab.state(name)["resources"]["agent"] != original
        assert cli("shell", name, check=False).returncode == exit_code
        lab.assert_removed(name)


def test_temporary_run_rejects_existing_name_without_changes(lab):
    project, path = lab.project()
    name = lab.start(project, command=["sh", "-c", "touch /workspace/must-not-run"])
    before = lab.state(name)["resources"]
    result = cli("run", str(lab.environments[name]), check=False)
    assert result.returncode == 2 and "already exists" in result.stderr
    assert lab.state(name)["resources"] == before
    assert not (path / "must-not-run").exists()
    cli("exec", name, "--", "true")


def test_temporary_run_terminal_input_and_size(lab):
    project, _ = lab.project()
    name, config = lab.configuration(
        project,
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
    assert "size=83x33" in result.stdout
    assert "reply:tupni-lanimret" in result.stdout
    lab.assert_removed(name)


@pytest.mark.parametrize("operation", ["run", "shell"])
@pytest.mark.parametrize("terminal", [False, True])
def test_temporary_run_ctrl_c_cleans_up_without_blocking_other_environment(
    lab, terminal, operation
):
    project, path = lab.project()
    other = lab.start(project)
    name, config = lab.configuration(
        project,
        persistent=operation != "shell",
        command=["sh", "-c", "touch /workspace/run-ready; sleep 60"],
    )
    if operation == "shell":
        cli("start", str(config))
    arguments = ["/usr/local/bin/abx", operation, name if operation == "shell" else str(config)]
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
    try:
        for _ in range(100):
            if (path / "run-ready").exists():
                break
            assert process.poll() is None
            time.sleep(0.1)
        else:
            pytest.fail("Temporary command did not start")
        assert name in json.loads(cli("status", timeout=5).stdout)
        if operation == "shell":
            original = lab.state(name)["resources"]["agent"]
            cli("start", str(config))
            cli("proxy", "apply", str(config))
            state = lab.state(name)
            assert state["shell_active"] is True
            assert state["resources"]["agent"] == original
            rejected = cli("shell", name, check=False, timeout=5)
            assert rejected.returncode == 2 and "already claimed" in rejected.stderr
        cli("exec", other, "--", "true", timeout=5)
        if terminal:
            process.stdin.write("\x03")
            process.stdin.flush()
        else:
            process.send_signal(signal.SIGINT)  # Target the CLI, not its entire process group.
        stdout, stderr = process.communicate(timeout=30)
        assert process.returncode == 130, stdout + stderr
        assert "Traceback" not in stdout + stderr
        lab.assert_removed(name)
        cli("exec", other, "--", "true")
    finally:
        if process.poll() is None:
            cli("remove", name, check=False)
            process.terminate()
            process.wait(timeout=10)


def test_stop_removes_nonpersistent_environment(lab):
    project, path = lab.project()
    name = lab.start(project, persistent=False)
    cli("exec", name, "--", "sh", "-c", "touch /home/agent/dirty /workspace/kept")
    assert json.loads(cli("stop", name).stdout)["status"] == "removed"
    lab.assert_removed(name)
    assert (path / "kept").exists()
