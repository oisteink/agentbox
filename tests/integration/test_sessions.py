"""Actual concurrent CLI sessions against the installed rootless Docker instance."""

import json
import subprocess
import time

import pytest
from conftest import cli


def snapshot(name=None):
    data = json.loads(cli("status").stdout)
    return data.get(name) if name is not None else data


def wait_for(probe, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = probe()
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for installed session state")


def spawn(config, *, command=None, keep=False, isolated=False):
    args = ["/usr/local/bin/abx", "exec" if command else "start", str(config)]
    if keep:
        args.append("--keep-running")
    if command:
        args += ["--", *command]
    return subprocess.Popen(
        args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=isolated,
    )


def complete(process, expected=0):
    out, err = process.communicate(input="", timeout=30)
    assert process.returncode == expected, (process.returncode, out, err)
    return out, err


def cleanup_processes(name, processes):
    if any(process.poll() is None for process in processes):
        cli("stop", name, check=False)
    for process in processes:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=10)


@pytest.mark.parametrize("order", [(0, 1), (1, 0)])
@pytest.mark.parametrize("keep", [False, True])
@pytest.mark.parametrize("persistent", [False, True])
def test_two_sessions_last_exit_and_late_shared_keep(lab, order, keep, persistent):
    source, path = lab.mount()
    name, config = lab.configuration(source, persistent=persistent)
    processes = []
    try:
        for index in range(2):
            command = [
                "sh",
                "-c",
                f"touch /workspace/ready-{index}; while [ ! -e /workspace/release-{index} ]; do sleep .05; done",
            ]
            processes.append(spawn(config, command=command, keep=keep and index == 1))
            wait_for(lambda: (path / f"ready-{index}").exists())
        entry = snapshot(name)
        identifier = entry["resources"]["agent"]
        period = entry["runtime"]["generation"]
        assert len(entry["runtime"]["sessions"]) == 2 and entry["runtime"]["keep_running"] is keep
        first, last = order
        (path / f"release-{first}").touch()
        complete(processes[first])
        entry = snapshot(name)
        assert entry["resources"]["agent"] == identifier and entry["status"] == "running"
        assert len(entry["runtime"]["sessions"]) == 1
        (path / f"release-{last}").touch()
        complete(processes[last])
        entry = snapshot(name)
        if keep:
            assert entry["runtime"]["generation"] == period and entry["runtime"]["sessions"] == {}
            cli("exec", str(config), "--keep-running", "--", "true")
            cli("exec", str(config), "--", "true")
            assert snapshot(name)["resources"]["agent"] == identifier
            cli("stop", name)
        elif persistent:
            assert entry["status"] == "stopped" and "runtime" not in entry
        else:
            lab.assert_removed(name)
        if not persistent:
            lab.assert_removed(name)
        assert (path / "ready-0").exists() and (path / "ready-1").exists()
    finally:
        cleanup_processes(name, processes)


def test_explicit_stop_and_old_finally_preserve_new_period_same_container(lab):
    source, path = lab.mount()
    name, config = lab.configuration(source)
    process = spawn(config, command=["sh", "-c", "touch /workspace/ready; sleep 60"], isolated=True)
    helper = None
    try:
        wait_for(lambda: (path / "ready").exists())
        entry = wait_for(
            lambda: (value if (value := snapshot(name)) and not value.get("launches") else None)
        )
        runtime = entry["runtime"]
        original = entry["resources"]["agent"]
        helper = next(iter(runtime["sessions"].values()))["helper"]["pid"]
        subprocess.run(["sudo", "kill", "-STOP", str(helper)], check=True)
        cli("stop", name)
        cli("exec", str(config), "--keep-running", "--", "touch", "/workspace/new-period")
        newer = snapshot(name)
        assert newer["resources"]["agent"] == original
        assert newer["runtime"]["generation"] != runtime["generation"]
        subprocess.run(["sudo", "kill", "-CONT", "--", str(helper), f"-{process.pid}"], check=True)
        helper = None
        out, err = process.communicate(input="", timeout=30)
        assert process.returncode != 0, (out, err)
        assert snapshot(name)["runtime"]["generation"] == newer["runtime"]["generation"]
        assert snapshot(name)["status"] == "running" and (path / "new-period").exists()
    finally:
        if helper is not None:
            subprocess.run(
                ["sudo", "kill", "-CONT", "--", str(helper), f"-{process.pid}"], check=False
            )
        cleanup_processes(name, [process])


@pytest.mark.parametrize(
    "victim,persistent,keep",
    [
        ("client", True, False),
        ("client", False, False),
        ("client", True, True),
        ("helper", True, False),
    ],
)
def test_watcher_reaps_crashed_sessions(lab, victim, persistent, keep):
    source, path = lab.mount()
    name, config = lab.configuration(
        source, persistent=persistent, command=["sh", "-c", "touch /workspace/ready; sleep 60"]
    )
    process = spawn(config, keep=keep)
    try:
        wait_for(lambda: (path / "ready").exists())
        entry = wait_for(
            lambda: (value if (value := snapshot(name)) and not value.get("launches") else None)
        )
        if victim == "client":
            process.kill()
        else:
            helper = next(iter(entry["runtime"]["sessions"].values()))["helper"]["pid"]
            subprocess.run(["sudo", "kill", "-KILL", str(helper)], check=True)
        out, err = process.communicate(timeout=30)
        assert process.returncode != 0, (out, err)
        if keep:
            entry = wait_for(
                lambda: (
                    value
                    if (value := snapshot(name)) and value.get("runtime", {}).get("sessions") == {}
                    else None
                )
            )
            assert entry["status"] == "running" and entry["runtime"]["keep_running"]
            cli("stop", name)
        elif persistent:
            wait_for(
                lambda: (
                    value if (value := snapshot(name)) and value["status"] == "stopped" else None
                )
            )
        else:
            wait_for(lambda: snapshot(name) is None)
            lab.assert_removed(name)
        assert (path / "ready").exists()
    finally:
        cleanup_processes(name, [process])


def test_parallel_runs_are_visible_and_do_not_affect_normal_environment(lab):
    import yaml

    source, path = lab.mount()
    name = lab.start(source)
    original = snapshot(name)["resources"]
    config = lab.environments[name]
    data = yaml.safe_load(config.read_text())
    data["command"] = [
        "python3",
        "-c",
        "import sys; print('run-ready',flush=True); sys.stdin.read(); print('run-done')",
    ]
    config.write_text(yaml.safe_dump(data))
    processes = [
        subprocess.Popen(
            ["/usr/local/bin/abx", "run", str(config)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    active = {}
    try:

        def running_instances():
            rows = {
                key: value
                for key, value in snapshot().items()
                if key.startswith(name[:31] + "-run-")
            }
            return (
                rows
                if len(rows) == 2 and all(not value.get("launches") for value in rows.values())
                else None
            )

        active = wait_for(running_instances)
        by_pid = {
            next(iter(value["runtime"]["sessions"].values()))["client"]["pid"]: key
            for key, value in active.items()
        }
        first, second = by_pid[processes[0].pid], by_pid[processes[1].pid]
        assert first != second and snapshot(name)["resources"] == original
        for key in (first, second):
            wait_for(lambda key=key: "run-ready" in cli("logs", key).stdout)
        cli("stop", first)
        out, err = processes[0].communicate(timeout=30)
        assert processes[0].returncode != 0, (out, err)
        lab.assert_removed(first)
        assert snapshot(second)["status"] == "running" and processes[1].poll() is None
        complete(processes[1])
        lab.assert_removed(second)
        assert snapshot(name)["resources"] == original
        cli("exec", str(config), "--", "touch", "/workspace/retained")
        assert (path / "retained").exists()
    finally:
        for key in active:
            cli("remove", key, check=False)
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=10)


def test_stopped_nonpersistent_layer_is_replaced_after_interrupted_cleanup(lab):
    source, path = lab.mount()
    name = lab.start(source, persistent=False)
    identifier = snapshot(name)["resources"]["agent"]
    cli(
        "exec",
        str(lab.environments[name]),
        "--",
        "sh",
        "-c",
        "touch /home/agent/dirty; echo retained > /workspace/retained",
    )
    lab.docker("container", "stop", identifier)
    result = cli(
        "exec",
        str(lab.environments[name]),
        "--",
        "sh",
        "-c",
        "test ! -e /home/agent/dirty; cat /workspace/retained",
    )
    assert result.stdout == "retained\n"
    assert lab.docker("container", "inspect", identifier, check=False).returncode != 0
    lab.assert_removed(name)
    assert (path / "retained").read_text() == "retained\n"
