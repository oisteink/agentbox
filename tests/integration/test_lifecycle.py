"""Independent installed-CLI scenarios, each with its own resources and cleanup."""

import json
import os
import pwd
import shlex
import subprocess
import time

import pytest
import yaml
from conftest import cli


def python(env, source, *arguments):
    # CLI arguments are single-line strings; repr preserves a multiline Python program.
    return cli("exec", env, "--", "python3", "-c", f"exec({source!r})", *arguments)


@pytest.mark.parametrize(
    "image,tool,version",
    [("opencode", "opencode", "1.19.5"), ("claude-code", "claude", "2.1.316")],
)
def test_example_agent_version_in_isolation(lab, image, tool, version):
    mount, _ = lab.mount()
    env = lab.start(mount, image=image, resources={"cpus": 1, "memory": "1g", "pids": 128})
    assert version in cli("exec", env, "--", tool, "--version").stdout


def test_two_images_and_independent_environments(lab):
    first, first_path = lab.mount("first")
    second, second_path = lab.mount("second")
    (second_path / "marker").write_text("second environment")
    env1 = lab.start(first, image="codex")
    env2 = lab.start(second)
    assert cli("exec", env1, "--", "codex", "--version").stdout.strip() == "codex-cli 0.166.0"
    # Re-registering an unchanged, in-use mount must be harmless.
    result = json.loads(cli("mount", "add", first, str(first_path)).stdout)
    assert result["status"] == "active"
    cli("stop", env1)
    cli("remove", env1)
    lab.assert_removed(env1)
    assert lab.state(env2)["containers"] == {"agent": "running", "proxy": "running"}
    assert cli("exec", env2, "--", "cat", "/workspace/marker").stdout == "second environment"


def test_local_image_build_context_and_use_guard(lab):
    name, recipe = lab.image()
    (recipe / "Dockerfile").write_text("FROM agentbox-image-smoke:local\nCOPY . /recipe/\n")
    (recipe / ".dockerignore").write_text("ignored\n")
    (recipe / "marker").write_text("first")
    (recipe / "ignored").write_text("must not be copied")
    assert json.loads(cli("image", "list").stdout)[name]["status"] == "unbuilt"
    mount, path = lab.mount()
    volume = lab.volume()
    (path / "keep").write_text("mount content")
    env = lab.start(
        mount,
        image=name,
        mounts=[
            {"source": mount, "target": "/workspace"},
            {"source": volume, "target": "/profile"},
        ],
    )
    first = json.loads(cli("image", "inspect", name).stdout)["id"]
    original = lab.state(env)["resources"]["agent"]
    cli("exec", env, "--", "sh", "-c", "echo retained > /profile/data; touch /home/agent/layer")
    assert cli("exec", env, "--", "cat", "/recipe/marker").stdout == "first"
    cli("exec", env, "--", "test", "!", "-e", "/recipe/ignored")
    (recipe / "marker").write_text("second")
    assert json.loads(cli("image", "list").stdout)[name]["status"] == "stale"
    pending = cli("start", str(lab.environments[env]))
    assert "next startup" in pending.stderr
    assert lab.state(env)["resources"]["agent"] == original
    assert cli("exec", env, "--", "cat", "/recipe/marker").stdout == "first"
    for operation in ("build", "remove"):
        blocked = cli("image", operation, name, check=False)
        assert blocked.returncode != 0 and "Image is in use" in blocked.stderr
    cli("stop", env)
    blocked_proxy = cli("proxy", "build", check=False)
    assert blocked_proxy.returncode != 0 and "Image is in use" in blocked_proxy.stderr
    second = json.loads(cli("image", "build", name, timeout=900).stdout)["id"]
    assert first != second
    assert cli("image", "remove", name, check=False).returncode != 0
    assert env in json.loads(cli("image", "inspect", name).stdout)["environments"]
    cli("start", str(lab.environments[env]))
    assert lab.state(env)["resources"]["agent"] != original
    assert cli("exec", env, "--", "cat", "/recipe/marker").stdout == "second"
    assert cli("exec", env, "--", "cat", "/profile/data").stdout == "retained\n"
    assert (path / "keep").read_text() == "mount content"
    cli("exec", env, "--", "test", "!", "-e", "/home/agent/layer")
    cli("remove", env)
    lab.assert_removed(env)
    cli("image", "remove", name)
    assert (recipe / "Dockerfile").is_file()
    listed = json.loads(cli("image", "list").stdout)[name]
    assert listed["status"] == "unbuilt" and "containers" not in listed


def test_edit_image_uses_operator_editor_and_returns_status(lab):
    name, recipe = lab.image()
    editor = lab.root / "test editor.py"
    editor.write_text(
        "import os, sys\n"
        "from pathlib import Path\n"
        f"assert os.getuid() == {os.getuid()}\n"
        "path = Path(sys.argv[-1])\n"
        "assert path.is_absolute() and path.parent == Path.cwd()\n"
        "assert sys.argv[1:-1] == ['quoted argument']\n"
        "assert input() == 'terminal input'\n"
        "path.write_text('FROM ubuntu:24.04\\n# edited\\n')\n"
        "print('editor output')\n"
        "sys.exit(19)\n"
    )
    environment = dict(
        os.environ,
        VISUAL=shlex.join(["python3", str(editor), "quoted argument"]),
        EDITOR="/missing-editor",
    )
    result = cli("image", "edit", name, input="terminal input\n", env=environment, check=False)
    assert result.returncode == 19
    assert result.stdout == "editor output\n"
    assert (recipe / "Dockerfile").read_text() == "FROM ubuntu:24.04\n# edited\n"
    assert json.loads(cli("image", "inspect", name).stdout)["status"] == "unbuilt"


def test_exec_exit_status_and_configured_shell(lab):
    mount, _ = lab.mount()
    env = lab.start(mount, command=["python3", "-c", "print('configured-shell')"])
    assert cli("shell", env).stdout == "configured-shell\n"
    result = cli(
        "exec",
        env,
        "--",
        "python3",
        "-c",
        "import sys; print(repr(sys.argv[1])); print('child-stderr', file=sys.stderr); sys.exit(23)",
        "argument with spaces",
        check=False,
    )
    assert result.returncode == 23, result
    assert "'argument with spaces'\n" in result.stdout
    assert "child-stderr\n" in result.stderr
    assert "child-stderr" in cli("logs", env).stdout


def test_terminal_reads_input_and_preserves_size(lab):
    mount, _ = lab.mount()
    env = lab.start(mount)
    program = (
        "import os; assert os.isatty(0) and os.isatty(1); "
        "print('size=%sx%s' % tuple(os.get_terminal_size(1)), flush=True); "
        "print('reply:' + input()[::-1], flush=True)"
    )
    command = shlex.join(["/usr/local/bin/abx", "exec", env, "--", "python3", "-c", program])
    result = subprocess.run(
        ["script", "-q", "-e", "-c", "stty rows 30 cols 100; exec " + command, "/dev/null"],
        input="operator-input\n",
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "size=100x30" in result.stdout
    assert "reply:tupni-rotarepo" in result.stdout  # Cannot be satisfied by terminal echo.


def test_mount_file_operations_and_remove_preserve_code(lab):
    mount, path = lab.mount()
    (path / "from-developer").write_text("developer")
    (path / "executable").write_text("#!/bin/sh\nprintf executable")
    (path / "executable").chmod(0o750)
    env = lab.start(mount)
    cli(
        "exec",
        env,
        "--",
        "python3",
        "-c",
        "from pathlib import Path; "
        "p=Path('/workspace/from-developer'); assert p.read_text() == 'developer'; "
        "p.write_text('edited-by-agent'); Path('/workspace/from-agent').write_text('agent'); "
        "Path('/workspace/new-directory').mkdir(); "
        "Path('/workspace/new-directory/file').write_text('nested')",
    )
    assert (path / "from-developer").read_text() == "edited-by-agent"
    assert not (path / "from-agent").stat().st_mode & 0o111
    (path / "replacement").write_text("replaced-by-developer")
    (path / "replacement").replace(path / "from-agent")
    assert cli("exec", env, "--", "cat", "/workspace/from-agent").stdout == "replaced-by-developer"
    assert cli("exec", env, "--", "/workspace/executable").stdout == "executable"
    (path / "new-directory/file").unlink()
    cli("exec", env, "--", "rm", "/workspace/from-developer")
    assert not (path / "from-developer").exists()
    cli("remove", env)
    lab.assert_removed(env)
    assert (path / "from-agent").read_text() == "replaced-by-developer"
    assert (path / "executable").stat().st_mode & 0o111
    assert json.loads(cli("mount", "list").stdout)[mount]["status"] == "active"


def test_mount_visibility_and_readonly(lab):
    mount, path = lab.mount()
    readonly, readonly_path = lab.mount("readonly")
    (path / "visible").write_text("selected mount")
    (readonly_path / "file").write_text("unchanged")
    hidden = lab.root / "hidden"
    hidden.mkdir()
    (hidden / "private").write_text("not shared")
    env = lab.start(
        mount,
        mounts=[
            {"source": mount, "target": "/workspace"},
            {"source": readonly, "target": "/readonly", "mode": "ro"},
        ],
    )
    result = python(
        env,
        "import errno, pathlib, sys; "
        "assert pathlib.Path('/workspace/visible').read_text() == 'selected mount'; "
        "assert not pathlib.Path(sys.argv[1]).exists(); "
        "assert pathlib.Path('/readonly/file').read_text() == 'unchanged'; "
        "\ntry: pathlib.Path('/readonly/file').write_text('bad')"
        "\nexcept OSError as e: assert e.errno == errno.EROFS; print('readonly-enforced')"
        "\nelse: raise AssertionError('write succeeded')",
        str(hidden),
    )
    assert result.stdout == "readonly-enforced\n"
    assert (readonly_path / "file").read_text() == "unchanged"


def test_acl_repair_and_revocation_leave_other_mount_working(lab):
    mount, path = lab.mount()
    other, other_path = lab.mount("other")
    (other_path / "marker").write_text("other mount")
    env = lab.start(
        mount,
        mounts=[
            {"source": mount, "target": "/workspace"},
            {"source": other, "target": "/readonly", "mode": "ro"},
        ],
    )
    revoked = cli("mount", "revoke", other)
    assert env in revoked.stderr and "open file handles" in revoked.stderr
    assert json.loads(cli("mount", "list").stdout)[other]["status"] == "revoked"
    cli("stop", env)
    cli("mount", "add", other, str(other_path))
    cli("start", str(lab.environments[env]))
    assert cli("exec", env, "--", "cat", "/readonly/marker").stdout == "other mount"
    cli(
        "exec",
        env,
        "--",
        "sh",
        "-c",
        "printf retained > /workspace/private; chmod 0600 /workspace/private",
    )
    with pytest.raises(PermissionError):
        (path / "private").read_text()
    assert (
        "private"
        in json.loads(cli("mount", "check", mount, check=False).stdout)["operator_access_issues"]
    )
    cli("stop", env)
    own_readonly = path / "operator-readonly"
    own_readonly.write_text("readonly")
    own_readonly.chmod(0o400)
    cli("mount", "check", mount, "--fix")
    own_readonly.write_text("owner access repaired")
    assert (path / "private").read_text() == "retained"
    checked = json.loads(cli("mount", "check", mount).stdout)
    assert not checked["operator_access_issues"] and not checked["service_access_issues"]
    other_env = lab.start(other)
    cli("remove", env)
    assert json.loads(cli("mount", "revoke", mount).stdout)["status"] == "revoked"
    # Observe traversal as the service identity, even though it owns this file.
    denied = subprocess.run(
        [
            "sudo",
            "-u",
            "agentbox",
            "python3",
            "-c",
            "import errno, pathlib, sys\ntry: pathlib.Path(sys.argv[1]).read_text()"
            "\nexcept OSError as e: assert e.errno == errno.EACCES; print('access-revoked')"
            "\nelse: raise AssertionError('access retained')",
            str(path / "private"),
        ],
        text=True,
        capture_output=True,
        timeout=30,
    )
    assert denied.returncode == 0, denied.stderr
    assert denied.stdout == "access-revoked\n"
    assert (path / "private").read_text() == "retained"
    assert cli("exec", other_env, "--", "cat", "/workspace/marker").stdout == "other mount"


def test_stop_start_preserves_container_and_home(lab):
    mount, path = lab.mount()
    (path / "code").write_text("mount survives")
    env = lab.start(mount)
    before = lab.state(env)["resources"]
    cli("exec", env, "--", "sh", "-c", "printf home-survives > /home/agent/marker")
    cli("start", str(lab.environments[env]))
    assert lab.state(env)["resources"] == before  # Running start is idempotent, too.
    cli("stop", env)
    cli("stop", env)
    assert lab.state(env)["containers"] == {"agent": "exited", "proxy": "exited"}
    cli("start", str(lab.environments[env]))
    assert lab.state(env)["resources"]["agent"] == before["agent"]
    assert cli("exec", env, "--", "cat", "/home/agent/marker").stdout == "home-survives"
    assert cli("exec", env, "--", "cat", "/workspace/code").stdout == "mount survives"


def test_changed_profile_waits_for_restart_and_recreates_container(lab):
    mount, path = lab.mount()
    (path / "data").write_text("retained")
    env = lab.start(mount)
    before = lab.state(env)["resources"]["agent"]
    cli("exec", env, "--", "sh", "-c", "printf retained > /home/agent/marker")
    config = lab.environments[env]
    modified = yaml.safe_load(config.read_text())
    modified["resources"]["pids"] = 128
    config.write_text(yaml.safe_dump(modified))
    assert "next startup" in cli("start", str(config)).stderr
    assert lab.state(env)["resources"]["agent"] == before
    assert cli("exec", env, "--", "cat", "/home/agent/marker").stdout == "retained"
    cli("stop", env)
    cli("start", str(config))
    assert lab.state(env)["resources"]["agent"] != before
    cli("exec", env, "--", "test", "!", "-e", "/home/agent/marker")
    assert cli("exec", env, "--", "cat", "/sys/fs/cgroup/pids.max").stdout == "128\n"
    assert (path / "data").read_text() == "retained"


def test_socket_capability_and_cgroup_enforcement(lab):
    mount, _ = lab.mount()
    env = lab.start(mount)
    result = python(
        env,
        "import asyncio, errno, pathlib, socket; "
        "assert not pathlib.Path('/var/run/docker.sock').exists(); "
        "asyncio.run(asyncio.sleep(0)); "
        "assert pathlib.Path('/proc/sys/net/ipv6/conf/all/disable_ipv6').read_text().strip() == '1'; "
        "p=pathlib.Path('/sys/fs/cgroup'); "
        "assert {n:(p/n).read_text().strip() for n in ['cpu.max','memory.max','pids.max']} "
        "== {'cpu.max':'50000 100000', 'memory.max':'268435456', 'pids.max':'64'}; "
        "\ntry: socket.socket(socket.AF_UNIX)"
        "\nexcept OSError as e: assert e.errno == errno.EPERM; print('socket-denied')"
        "\nelse: raise AssertionError('Unix socket allowed')",
    )
    assert result.stdout == "socket-denied\n"
    denied = cli("exec", env, "--", "ip", "link", "add", "forbidden", "type", "dummy", check=False)
    assert denied.returncode != 0 and "Operation not permitted" in denied.stderr
    limited = python(
        env,
        """
import errno, os, signal, time
from pathlib import Path
children = []
try:
    for attempt in range(80):
        try:
            pid = os.fork()
        except OSError as exc:
            assert exc.errno == errno.EAGAIN
            assert int(Path('/sys/fs/cgroup/pids.current').read_text()) == 64
            print('pids-enforced', flush=True)
            break
        if pid == 0:
            time.sleep(10)
            os._exit(0)
        children.append(pid)
    else:
        raise AssertionError('process limit not enforced')
finally:
    for pid in children:
        os.kill(pid, signal.SIGTERM)
    for pid in children:
        os.waitpid(pid, 0)
""",
    )
    assert limited.stdout == "pids-enforced\n"
    assert cli("exec", env, "--", "true").returncode == 0


def test_environment_network_isolation(lab):
    first, _ = lab.mount("first")
    second, path = lab.mount("second")
    (path / "marker").write_text("controlled-service")
    env1, env2 = lab.start(first), lab.start(second)
    cli("exec", env2, "--", "sh", "-c", "python3 -m http.server 18482 >/tmp/http.log 2>&1 &")
    address = cli(
        "exec",
        env2,
        "--",
        "python3",
        "-c",
        "import socket; print(socket.gethostbyname(socket.gethostname()))",
    ).stdout.strip()
    control_args = [
        "exec",
        env2,
        "--",
        "curl",
        "--fail",
        "--silent",
        "--noproxy",
        "*",
        "--retry",
        "3",
        "--retry-connrefused",
        f"http://{address}:18482/marker",
    ]
    assert cli(*control_args).stdout == "controlled-service"
    result = python(
        env1,
        "import errno, socket, sys"
        "\ntry: socket.create_connection((sys.argv[1],18482),timeout=2)"
        "\nexcept OSError as e: assert e.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ETIMEDOUT) "
        "or isinstance(e, TimeoutError); print('network-isolated')"
        "\nelse: raise AssertionError('other environment reached')",
        address,
    )
    assert result.stdout == "network-isolated\n"
    assert cli(*control_args).stdout == "controlled-service"


def test_daemon_restart_preserves_home(lab):
    mount, _ = lab.mount()
    env = lab.start(mount)
    before = lab.state(env)["resources"]["agent"]
    cli("exec", env, "--", "sh", "-c", "printf retained > /home/agent/marker")
    uid = pwd.getpwnam("agentbox").pw_uid
    systemctl = [
        "sudo",
        "-u",
        "agentbox",
        "env",
        "HOME=/var/lib/agentbox",
        f"XDG_RUNTIME_DIR=/run/user/{uid}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{uid}/bus",
        "systemctl",
        "--user",
    ]
    subprocess.run(
        [*systemctl, "restart", "docker.service"], check=True, capture_output=True, timeout=45
    )
    for _ in range(50):
        guard = subprocess.run(
            [*systemctl, "is-active", "agentbox-watch.service"], capture_output=True, timeout=5
        )
        if guard.returncode == 0 and cli("doctor", check=False).returncode == 0:
            break
        time.sleep(0.2)
    else:
        pytest.fail("daemon/address guard did not recover")
    cli("start", str(lab.environments[env]))
    assert lab.state(env)["resources"]["agent"] == before
    assert cli("exec", env, "--", "cat", "/home/agent/marker").stdout == "retained"
