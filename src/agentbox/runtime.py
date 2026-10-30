"""Pinned local daemon access. All subprocesses use a clean environment and argv."""

import fcntl
import json
import os
import stat
import subprocess
from pathlib import Path

from .errors import AgentboxError


def local_addresses():
    output = subprocess.run(
        ["/usr/sbin/ip", "-j", "address", "show"], text=True, capture_output=True, check=True
    )
    return sorted(
        {
            entry["local"]
            for interface in json.loads(output.stdout)
            for entry in interface.get("addr_info", [])
        }
    )


class Docker:
    def __init__(self, uid, home):
        self.uid = uid
        self.home = home
        self.socket = Path(f"/run/user/{uid}/docker.sock")
        self.expected_id = None

    def run(
        self, *arguments, check=True, interactive=False, source=None, timeout=120, terminal=None
    ):
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": self.home,
            "XDG_RUNTIME_DIR": f"/run/user/{self.uid}",
            "LANG": "C.UTF-8",
        }
        result = subprocess.run(
            ["/usr/bin/docker", "--host", f"unix://{self.socket}", *arguments],
            env=env,
            text=True,
            input=source,
            stdin=terminal,
            capture_output=not interactive,
            timeout=timeout,
            check=False,
        )
        if check and result.returncode:
            # Docker errors must never include command values supplied as credentials.
            raise AgentboxError(
                f"Docker {' '.join(arguments[:2])} failed: {(result.stderr or '').strip()}"
            )
        return result

    def inspect(self, kind, identifier):
        return json.loads(self.run(kind, "inspect", identifier).stdout)[0]

    def verify(self, expected_id=None):
        if os.getuid() != self.uid:
            raise AgentboxError("Control helper must run as the service user")
        metadata = self.socket.lstat()
        if (
            not stat.S_ISSOCK(metadata.st_mode)
            or metadata.st_uid != self.uid
            or metadata.st_mode & 0o007
        ):
            raise AgentboxError("Unexpected Docker socket owner, type or permissions")
        info = json.loads(self.run("info", "--format", "{{json .}}").stdout)
        if "name=rootless" not in info.get("SecurityOptions", []):
            raise AgentboxError("Refusing a daemon that is not rootless")
        if info.get("CgroupVersion") != "2" or info.get("CgroupDriver") != "systemd":
            raise AgentboxError("cgroup v2 with systemd is required")
        if Path(info["DockerRootDir"]).resolve().is_relative_to(Path(self.home).resolve()) is False:
            raise AgentboxError("Docker data is outside the service home")
        if expected_id and info["ID"] != expected_id:
            raise AgentboxError("Daemon ID changed; reinitialization is required")
        version = tuple(int(n) for n in info["ServerVersion"].split(".")[:2])
        if version < (28, 0):
            raise AgentboxError("Docker 28 or newer is required for isolated gateway mode")
        warnings = " ".join(info.get("Warnings") or []).lower()
        if any(s in warnings for s in ("no cpu", "no memory", "no pids")):
            raise AgentboxError("Docker reports missing resource limit support")
        self.expected_id = info["ID"]
        return info

    def mutate(self, *arguments, **kwargs):
        self.verify(self.expected_id)
        return self.run(*arguments, **kwargs)

    def exec_stream(self, identifier, command, log_directory, terminal=None):
        arguments = ["exec"] + (["-it"] if terminal else []) + [identifier, *command]
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": self.home,
            "XDG_RUNTIME_DIR": f"/run/user/{self.uid}",
            "LANG": "C.UTF-8",
        }
        process = subprocess.Popen(
            ["/usr/bin/docker", "--host", f"unix://{self.socket}", *arguments],
            env=env,
            stdin=terminal or subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        directory = Path(log_directory)
        try:
            while block := os.read(process.stdout.fileno(), 4096):
                os.write(1, block)
                # Agent output is untrusted and can contain credentials. This
                # bounded log lives only in the private service state directory.
                lock = os.open(
                    directory / "log.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
                )
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    log = directory / "agent.log"
                    if log.exists() and log.stat().st_size + len(block) > 1_048_576:
                        older = directory / "agent.log.1"
                        if older.exists():
                            os.replace(older, directory / "agent.log.2")
                        os.replace(log, older)
                    fd = os.open(log, os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                    try:
                        os.write(fd, block)
                    finally:
                        os.close(fd)
                finally:
                    os.close(lock)
        except BaseException:
            process.terminate()
            raise
        finally:
            process.wait()
        return process.returncode
