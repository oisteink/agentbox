"""Pinned local daemon access. All subprocesses use a clean environment and argv."""

import codecs
import errno
import fcntl
import http.client
import json
import os
import pty
import re
import selectors
import signal
import socket
import stat
import subprocess
import termios
import time
import tty
from contextlib import ExitStack, contextmanager
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
        self.input_source = None
        self.output = None
        self.ready = None

    def run(
        self,
        *arguments,
        check=True,
        interactive=False,
        source=None,
        timeout=120,
        terminal=None,
        extra_env=None,
    ):
        env = {
            "PATH": "/usr/bin:/bin",
            "HOME": self.home,
            "XDG_RUNTIME_DIR": f"/run/user/{self.uid}",
            "LANG": "C.UTF-8",
        }
        if extra_env:
            env.update(extra_env)
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
            if extra_env:
                raise AgentboxError(
                    "Docker operation with proxy credentials failed; output withheld"
                )
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

    def launch_intent(self, identifier, deadline):
        baseline = (
            json.loads(
                self.run(
                    "container",
                    "inspect",
                    "--format",
                    "{{json .ExecIDs}}",
                    identifier,
                    timeout=remaining(deadline),
                ).stdout
            )
            or []
        )
        return {"agent": identifier, "baseline": baseline, "since": time.time_ns(), "exec": None}

    def exec_inspect(self, identifier, deadline):
        if not isinstance(identifier, str) or not re.fullmatch("[0-9a-f]{64}", identifier):
            raise AgentboxError("Invalid exec identity", code="launch_unknown")
        version = self._json_get("/version", deadline)["ApiVersion"]
        if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+", version):
            raise AgentboxError("Invalid Docker API version", code="launch_unknown")
        return self._json_get(f"/v{version}/exec/{identifier}/json", deadline)

    def _json_get(self, path, deadline):
        connection = http.client.HTTPConnection("localhost", timeout=remaining(deadline))
        connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            connection.sock.settimeout(remaining(deadline))
            connection.sock.connect(str(self.socket))
            connection.request("GET", path)
            connection.sock.settimeout(remaining(deadline))
            wire = connection.sock
            response = connection.getresponse()
            raw = bytearray()
            while True:
                wire.settimeout(remaining(deadline))
                block = response.read1(min(65536, 1_048_577 - len(raw)))
                if not block:
                    break
                raw.extend(block)
                if len(raw) > 1_048_576:
                    break
            if response.status != 200 or len(raw) > 1_048_576:
                raise AgentboxError("Docker exec observation failed", code="launch_unknown")
            result = json.loads(raw)
            if not isinstance(result, dict):
                raise AgentboxError("Invalid Docker exec observation", code="launch_unknown")
            return result
        finally:
            connection.close()

    def confirm_launch(self, intent, deadline, discovered):
        while True:
            remaining(deadline)
            identifier = intent.get("exec")
            if identifier is None:
                current = (
                    json.loads(
                        self.run(
                            "container",
                            "inspect",
                            "--format",
                            "{{json .ExecIDs}}",
                            intent["agent"],
                            timeout=remaining(deadline),
                        ).stdout
                    )
                    or []
                )
                candidates = set(current) - set(intent["baseline"])
                if not candidates:
                    until = time.time_ns()

                    def timestamp(ns):
                        return f"{ns // 1_000_000_000}.{ns % 1_000_000_000:09d}"

                    replay = self.run(
                        "events",
                        "--since",
                        timestamp(intent["since"]),
                        "--until",
                        timestamp(until),
                        "--filter",
                        "container=" + intent["agent"],
                        "--filter",
                        "event=exec_create",
                        "--format",
                        "{{json .}}",
                        timeout=remaining(deadline),
                    ).stdout
                    candidates = set()
                    for line in replay.splitlines():
                        event = json.loads(line)
                        actor = event["Actor"]
                        if actor["ID"] != intent["agent"] or not event["Action"].startswith(
                            "exec_create"
                        ):
                            raise AgentboxError("Unexpected exec event", code="launch_unknown")
                        candidate = actor["Attributes"]["execID"]
                        if candidate not in intent["baseline"]:
                            candidates.add(candidate)
                if len(candidates) > 1:
                    raise AgentboxError("Exec launch identity is ambiguous", code="launch_unknown")
                if candidates:
                    identifier = candidates.pop()
                    if not isinstance(identifier, str) or not re.fullmatch(
                        "[0-9a-f]{64}", identifier
                    ):
                        raise AgentboxError("Invalid exec identity", code="launch_unknown")
                    intent["exec"] = identifier
                    discovered()
            if identifier is not None:
                detail = self.exec_inspect(identifier, deadline)
                remaining(deadline)
                pid, code = detail.get("Pid"), detail.get("ExitCode")
                if detail.get("ID") != identifier or detail.get("ContainerID") != intent["agent"]:
                    raise AgentboxError("Exec launch identity changed", code="launch_unknown")
                if (type(pid) is int and pid > 0) or (
                    detail.get("Running") is False and type(code) is int
                ):
                    return
            time.sleep(min(0.02, remaining(deadline)))

    @contextmanager
    def execution(self, identifier, command, terminal=None):
        with ExitStack() as cleanup:
            output = subprocess.PIPE
            reader = None
            if terminal:
                reader, writer = pty.openpty()
                cleanup.callback(os.close, reader)
                output = cleanup.enter_context(os.fdopen(writer, "wb", buffering=0))
                tty.setraw(output.fileno())

                def resize(signum=None, frame=None):
                    termios.tcsetwinsize(reader, termios.tcgetwinsize(terminal.fileno()))

                resize()
                previous = signal.signal(signal.SIGWINCH, resize)
                cleanup.callback(signal.signal, signal.SIGWINCH, previous)
            arguments = ["exec"] + (
                ["-it"] if terminal else (["-i"] if self.input_source is not None else [])
            )
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": self.home,
                "XDG_RUNTIME_DIR": f"/run/user/{self.uid}",
                "LANG": "C.UTF-8",
            }
            process = subprocess.Popen(
                [
                    "/usr/bin/docker",
                    "--host",
                    f"unix://{self.socket}",
                    *arguments,
                    identifier,
                    *command,
                ],
                env=env,
                stdin=terminal or self.input_source or subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.STDOUT if terminal else subprocess.PIPE,
            )
            cleanup.callback(finish_process, process)
            if reader is not None:
                output.close()
            else:
                reader = process.stdout.fileno()
                cleanup.callback(process.stdout.close)
                cleanup.callback(process.stderr.close)
            yield Execution(self, process, reader, terminal)

    def exec_stream(self, identifier, command, log_directory, terminal=None):
        directory = os.open(log_directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            with self.execution(identifier, command, terminal) as execution:
                return execution.drain(directory)
        finally:
            os.close(directory)


def remaining(deadline):
    value = deadline - time.monotonic()
    if value <= 0:
        raise AgentboxError(
            "Exec launch was not confirmed within 10 seconds", code="launch_unknown"
        )
    return value


def finish_process(process):
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def append_log(directory, block):
    # A removed directory remains bound to this FD; never reopen a replacement.
    try:
        lock = os.open("log.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=directory)
        try:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                size = os.stat("agent.log", dir_fd=directory, follow_symlinks=False).st_size
            except FileNotFoundError:
                size = 0
            if size + len(block) > 1_048_576:
                try:
                    os.replace(
                        "agent.log.1", "agent.log.2", src_dir_fd=directory, dst_dir_fd=directory
                    )
                except FileNotFoundError:
                    pass
                os.replace("agent.log", "agent.log.1", src_dir_fd=directory, dst_dir_fd=directory)
            fd = os.open(
                "agent.log",
                os.O_CREAT | os.O_APPEND | os.O_WRONLY | os.O_NOFOLLOW,
                0o600,
                dir_fd=directory,
            )
            try:
                os.write(fd, block)
            finally:
                os.close(fd)
        finally:
            os.close(lock)
    except FileNotFoundError:
        pass  # Environment removal can unlink the selected log directory.


class Execution:
    def __init__(self, docker, process, reader, terminal):
        self.docker, self.process, self.reader, self.terminal = docker, process, reader, terminal

    def drain(self, directory):
        selector = selectors.PollSelector()
        selector.register(self.reader, selectors.EVENT_READ, "stdout")
        if not self.terminal:
            selector.register(self.process.stderr, selectors.EVENT_READ, "stderr")
        decoders = {
            name: codecs.getincrementaldecoder("utf-8")("replace") for name in ("stdout", "stderr")
        }
        try:
            while selector.get_map():
                key = selector.select()[0][0]
                try:
                    block = os.read(key.fd, 4096)
                except OSError as exc:
                    if self.terminal and exc.errno == errno.EIO:
                        block = b""
                    else:
                        raise
                if self.docker.output:
                    text = decoders[key.data].decode(block, final=not block)
                    if text:
                        self.docker.output(key.data, text)
                elif block:
                    os.write(2 if key.data == "stderr" else 1, block)
                if not block:
                    selector.unregister(key.fileobj)
                    continue
                append_log(directory, block)
            return self.process.wait()
        finally:
            selector.close()
