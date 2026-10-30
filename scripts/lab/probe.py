#!/usr/bin/env python3
"""Record baseline behavior in the disposable VM, including expected weaknesses.

This is a feasibility probe, not the MVP acceptance suite. Run as root in the
agentbox-lab VM after building agentbox-dev:lab. Resources are always removed.
"""

import json
import os
import pathlib
import pwd
import shutil
import socket
import subprocess
import tempfile
import uuid


def run(*args, check=True, **kwargs):
    return subprocess.run(args, check=check, text=True, capture_output=True, **kwargs)


def main():
    if os.geteuid() != 0 or socket.gethostname() != "agentbox-lab":
        raise SystemExit("Run only as root in the disposable agentbox-lab VM")
    account = pwd.getpwnam("agentbox")
    developer = pwd.getpwnam("developer")
    prefix = "agentbox-probe-" + uuid.uuid4().hex[:10]
    networks = []
    servers = []
    results = {}
    project = pathlib.Path(tempfile.mkdtemp(prefix=prefix, dir="/home/developer"))

    def docker(*args, **kwargs):
        return run(
            "runuser",
            "-u",
            "agentbox",
            "--",
            "env",
            "-i",
            "PATH=/usr/bin:/bin",
            "HOME=/var/lib/agentbox",
            f"XDG_RUNTIME_DIR=/run/user/{account.pw_uid}",
            "docker",
            "--host",
            f"unix:///run/user/{account.pw_uid}/docker.sock",
            *args,
            **kwargs,
        )

    def container(*args, code=None, check=True):
        command = [
            "run",
            "--rm",
            "--label",
            f"agentbox.probe={prefix}",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            *args,
            "agentbox-dev:lab",
        ]
        if code is not None:
            command.extend(["python3", "-c", code])
        return docker(*command, check=check, timeout=45)

    try:
        results["daemon"] = json.loads(docker("info", "--format", "{{json .}}").stdout)
        assert "name=rootless" in results["daemon"]["SecurityOptions"]
        for suffix, options in (
            (
                "internal",
                [
                    "--internal",
                    "--subnet",
                    "172.30.240.0/28",
                    "-o",
                    "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                ],
            ),
            ("external", []),
        ):
            name = prefix + "-" + suffix
            docker("network", "create", "--label", f"agentbox.probe={prefix}", *options, name)
            networks.append(name)
        internal, external = networks

        # Give only traversal through the developer home, and access to this fixture.
        original_home_acl = run("getfacl", "-p", "/home/developer").stdout
        run("setfacl", "-m", f"u:{account.pw_uid}:--x", "/home/developer")
        os.chown(project, developer.pw_uid, developer.pw_gid)
        run(
            "setfacl",
            "-m",
            f"u:{account.pw_uid}:rwx,d:u:{account.pw_uid}:rwx,d:u:{developer.pw_uid}:rwx",
            str(project),
        )

        mount = (
            f"type=bind,src={project},dst=/work,bind-recursive=disabled,bind-propagation=rprivate"
        )
        output = container(
            "--network",
            internal,
            "--mount",
            mount,
            code=(
                "import os,pathlib; p=pathlib.Path('/work/created'); p.write_text('agent'); "
                "print(open('/proc/self/uid_map').read()); print(os.getuid())"
            ),
        )
        results["uid_map"] = output.stdout
        results["new_file_owner"] = (project / "created").stat().st_uid
        assert results["new_file_owner"] == account.pw_uid
        run(
            "runuser",
            "-u",
            "developer",
            "--",
            "sh",
            "-c",
            'echo developer >> "$1"',
            "probe",
            str(project / "created"),
        )
        results["developer_can_edit_agent_file"] = True

        # Read-only must block UID 0, even though it maps to the file owner.
        readonly = container(
            "--network",
            internal,
            "--mount",
            mount + ",readonly",
            code="open('/work/created','w').write('bad')",
            check=False,
        )
        results["readonly_rejects_write"] = readonly.returncode != 0
        assert results["readonly_rejects_write"]

        dns_result = container(
            "--network",
            internal,
            code=(
                "import socket; socket.setdefaulttimeout(3); "
                "print(socket.getaddrinfo('example.com',443))"
            ),
            check=False,
        )
        results["internal_external_dns"] = {
            "exit": dns_result.returncode,
            "stdout": dns_result.stdout,
            "stderr": dns_result.stderr,
        }

        # Avoid the VM's QEMU subnet overlapping RootlessKit's slirp subnet.
        host_address = "198.18.240.1"
        run("ip", "address", "add", host_address + "/32", "dev", "lo")
        host_server = subprocess.Popen(
            [
                "python3",
                "-m",
                "http.server",
                "18481",
                "--bind",
                "0.0.0.0",
                "--directory",
                str(project),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        servers.append(host_server)
        connect = (
            "import socket; socket.setdefaulttimeout(3); "
            f"s=socket.create_connection(('{host_address}',18481)); print('connected')"
        )
        control = container("--network", external, code=connect, check=False)
        results["host_control"] = {
            "exit": control.returncode,
            "stdout": control.stdout,
            "stderr": control.stderr,
        }
        assert control.returncode == 0, "Host control endpoint must work before testing isolation"
        blocked = container("--network", internal, code=connect, check=False)
        results["host_from_internal"] = {
            "exit": blocked.returncode,
            "stdout": blocked.stdout,
            "stderr": blocked.stderr,
        }

        # A filesystem Unix socket crosses a directory bind mount despite network isolation.
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(project / "host.sock"))
        os.chmod(project / "host.sock", 0o666)
        listener.listen(2)
        unix_result = container(
            "--network",
            internal,
            "--mount",
            mount,
            code=(
                "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/work/host.sock'); print('connected')"
            ),
            check=False,
        )
        results["host_socket_through_mount"] = {
            "exit": unix_result.returncode,
            "stdout": unix_result.stdout,
            "stderr": unix_result.stderr,
        }
        listener.close()
        (project / "host.sock").unlink()

        profile = pathlib.Path("/var/lib/agentbox/lab-socket-profile.json")
        if profile.exists():
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(project / "host.sock"))
            os.chmod(project / "host.sock", 0o666)
            listener.listen(2)
            for operation in (
                "socket.socket(socket.AF_UNIX)",
                "socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)",
            ):
                guarded = container(
                    "--network",
                    internal,
                    "--mount",
                    mount,
                    "--security-opt",
                    f"seccomp={profile}",
                    code=("import socket; s=" + operation + "; print('unexpected socket')"),
                    check=False,
                )
                assert guarded.returncode != 0, operation
            # An actual filesystem connection through an already mounted
            # directory must fail as well, including via docker exec's profile.
            guarded = container(
                "--network",
                internal,
                "--mount",
                mount,
                "--security-opt",
                f"seccomp={profile}",
                code=(
                    "import socket; s=socket.socket(socket.AF_UNIX); s.connect('/work/host.sock')"
                ),
                check=False,
            )
            assert guarded.returncode != 0
            working = container(
                "--network",
                internal,
                "--security-opt",
                f"seccomp={profile}",
                code=(
                    "import asyncio,socket; a,b=socket.socketpair(); a.close(); b.close(); "
                    "asyncio.run(asyncio.sleep(0)); print('stream IPC and asyncio work')"
                ),
            )
            results["guarded_unix_sockets_blocked"] = True
            results["guarded_stream_ipc"] = working.stdout
            listener.close()
            (project / "host.sock").unlink()

        # Stream socketpair cannot be reconnected, datagram socketpair can.
        for kind in (socket.SOCK_STREAM, socket.SOCK_DGRAM):
            name = project / f"pair-{kind}.sock"
            server = socket.socket(socket.AF_UNIX, kind)
            server.bind(str(name))
            if kind == socket.SOCK_STREAM:
                server.listen()
            a, b = socket.socketpair(socket.AF_UNIX, kind)
            try:
                a.connect(str(name))
                results[f"socketpair_{kind}_reconnect"] = True
            except OSError as exc:
                results[f"socketpair_{kind}_reconnect"] = {"errno": exc.errno}
            finally:
                a.close()
                b.close()
                server.close()
                name.unlink()

        limited = container(
            "--network",
            internal,
            "--cpus",
            "0.5",
            "--memory",
            "128m",
            "--pids-limit",
            "32",
            code=(
                "import pathlib,json; p=pathlib.Path('/sys/fs/cgroup'); "
                "print(json.dumps({n:(p/n).read_text().strip() for n in ['cpu.max','memory.max','pids.max']}))"
            ),
        )
        results["cgroups"] = json.loads(limited.stdout)
        assert results["cgroups"]["memory.max"] == "134217728"
        assert results["cgroups"]["pids.max"] == "32"
        quota, period = results["cgroups"]["cpu.max"].split()
        assert int(quota) / int(period) == 0.5
        stress = container(
            "--network",
            internal,
            "--pids-limit",
            "12",
            "--memory",
            "128m",
            "--cpus",
            "0.5",
            code="""
import os, signal, time
children = []
try:
    for attempt in range(30):
        try:
            pid = os.fork()
        except BlockingIOError:
            print('pids-limit-enforced', len(children), flush=True)
            break
        if pid == 0:
            time.sleep(5)
            os._exit(0)
        children.append(pid)
    else:
        raise RuntimeError('PID limit was not enforced')
finally:
    for pid in children:
        os.kill(pid, signal.SIGTERM)
    for pid in children:
        os.waitpid(pid, 0)
""",
        )
        assert "pids-limit-enforced" in stress.stdout
        results["pids_limit_enforced"] = stress.stdout.strip()

        # Removing our named ACL does not revoke ownership rights on an agent-created file.
        run("setfacl", "-x", f"u:{account.pw_uid}", str(project / "created"))
        retained = run(
            "runuser", "-u", "agentbox", "--", "cat", str(project / "created"), check=False
        )
        results["file_owner_retains_access_after_named_acl_removal"] = retained.returncode == 0

        # The project root belongs to the developer. A named deny on this
        # directory blocks traversal, even when agentbox owns descendant files.
        run("setfacl", "-m", f"u:{account.pw_uid}:---", str(project))
        revoked = run(
            "runuser", "-u", "agentbox", "--", "cat", str(project / "created"), check=False
        )
        assert revoked.returncode != 0
        results["developer_owned_root_deny_revokes_path_access"] = True

    finally:
        for server in servers:
            server.terminate()
            server.wait(timeout=5)
        for network in reversed(networks):
            docker("network", "rm", network, check=False)
        if "host_address" in locals():
            run("ip", "address", "del", host_address + "/32", "dev", "lo", check=False)
        if "original_home_acl" in locals():
            run("setfacl", "--restore=-", input=original_home_acl)
        shutil.rmtree(project)
        print(json.dumps(results, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
