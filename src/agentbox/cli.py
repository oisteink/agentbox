"""Developer CLI and service-user entry point; control requests travel over stdin."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from . import completion, config, images, projects
from .control import Control
from .errors import AgentboxError
from .output import Output, failure, success, write_frame
from .process import pump
from .settings import load_settings
from .state import Store, atomic_json

_output = Output()


def rpc(request, stream=False, context=None):
    command = ["/usr/bin/sudo", "-H", "-u", "agentbox", "/usr/local/libexec/agentbox-control"]
    frames = []
    buffer = ""
    invalid = False

    def receive(channel, text):
        nonlocal buffer, invalid
        if channel == "stderr":
            return  # sudo diagnostics are not part of the authenticated result protocol.
        buffer += text
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            try:
                frame = json.loads(line)
                if frames or not isinstance(frame, dict):
                    raise ValueError
                if frame.get("type") == "result" and isinstance(frame.get("ok"), bool):
                    if not frame["ok"] and not (
                        isinstance(frame.get("error"), dict)
                        and isinstance(frame["error"].get("code"), str)
                        and isinstance(frame["error"].get("message"), str)
                    ):
                        raise ValueError
                    frames.append(frame)
                elif frame.get("type") == "output" and frame.get("stream") in ("stdout", "stderr"):
                    if not isinstance(frame.get("data"), str):
                        raise ValueError
                    _output.event(frame["stream"], frame["data"])
                else:
                    raise ValueError
            except (ValueError, TypeError):
                invalid = True

    header = (json.dumps(request) + "\n").encode()
    with tempfile.TemporaryFile() as source:
        if context is not None:
            source.write(header)
            images.archive(context, source)
            source.seek(0)
        child = subprocess.Popen(
            command,
            stdin=source if context is not None else subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        pump(
            child,
            receive,
            prefix=header if context is None else b"",
            source=sys.stdin.buffer if stream and not request.get("tty") else None,
        )
    if invalid or buffer or len(frames) != 1:
        raise AgentboxError(
            "Control helper did not return a complete result", code="control_protocol_error"
        )
    result = frames[0]
    if stream:
        return result
    if not result["ok"]:
        error = result["error"]
        raise AgentboxError(error["message"], code=error["code"], details=error.get("details"))
    return result.get("data")


def _fd(path):
    return os.open(path, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)


def project_update(settings, name, source):
    root = projects.validate_root(source, settings["operator_uid"])
    uids = {settings["operator_uid"], settings["service_uid"]}
    nodes = projects.scan(root, uids)
    existing = rpc({"action": "project", "operation": "list"}).get(name)
    if (
        existing
        and existing["status"] == "active"
        and existing["path"] == str(root)
        and existing["identity"] == projects.identity(root)
    ):
        checked = rpc({"action": "project", "operation": "check", "name": name})
        if not checked["service_access_issues"] and not projects.access_issues(root, uids):
            return checked
    # Validate every ACL change for files owned by this process before applying any.
    for node in nodes:
        if node["uid"] == os.getuid():
            with projects.node_fd(root, node) as fd:
                projects.grant_acl(
                    projects.read_acl(fd),
                    settings["service_uid"],
                    settings["operator_uid"],
                    node["directory"],
                    node["executable"],
                )
    local = Store(settings["operator_state"])
    with local.locked() as journal:
        rpc(
            {
                "action": "project",
                "operation": "prepare",
                "name": name,
                "path": str(root),
                "identity": projects.identity(root),
            }
        )
        journal.setdefault("parents", {})
        journal["projects"][name] = {"path": str(root), "status": "pending"}
        atomic_json(local.root / "state.json", journal)
        for parent in reversed(root.parents):
            if parent.stat().st_uid != os.getuid():
                continue
            fd = _fd(parent)
            try:
                before = projects.read_acl(fd)
                after = projects.named_acl(before, settings["service_uid"], "--x")
                record = journal["parents"].setdefault(
                    str(parent),
                    {
                        "before": before,
                        "identity": projects.identity(parent),
                        "projects": [],
                    },
                )
                if name not in record["projects"]:
                    record["projects"].append(name)
                atomic_json(local.root / "state.json", journal)
                projects.write_acl(fd, after)
                record["after"] = projects.read_acl(fd)
                atomic_json(local.root / "state.json", journal)
            finally:
                os.close(fd)
        projects.apply_owned(root, nodes, settings["service_uid"], settings["operator_uid"])
        result = rpc({"action": "project", "operation": "finish", "name": name})
        journal["projects"][name]["status"] = "active"
        return result


def project_revoke(settings, name):
    local = Store(settings["operator_state"])
    with local.locked() as journal:
        entry = rpc({"action": "project", "operation": "prepare-revoke", "name": name})
        root = projects.validate_root(entry["path"], settings["operator_uid"])
        if projects.identity(root) != entry["identity"]:
            raise AgentboxError("Project root changed; refusing ACL mutation")
        fd = _fd(root)
        try:
            projects.write_acl(
                fd, projects.named_acl(projects.read_acl(fd), settings["service_uid"], "---")
            )
        finally:
            os.close(fd)
        conflicts = []
        for path, record in list(journal.get("parents", {}).items()):
            if name not in record["projects"]:
                continue
            record["projects"].remove(name)
            if record["projects"]:
                continue
            fd = _fd(path)
            try:
                if projects.identity(path) == record["identity"] and projects.read_acl(
                    fd
                ) == record.get("after"):
                    projects.write_acl(fd, record["before"])
                    del journal["parents"][path]
                else:
                    conflicts.append(path)
            finally:
                os.close(fd)
        result = rpc({"action": "project", "operation": "revoked", "name": name})
        journal["projects"].setdefault(name, {})["status"] = "revoked"
        result["ancestor_acl_conflicts"] = conflicts
        result["note"] = "Root deny retained; descendant ACLs and file owners are unchanged"
        return result


class HelpRequested(Exception):
    def __init__(self, text):
        self.text = text


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.add_argument(
            "--json",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Emit JSON results; handled errors have exit status 0",
        )
        self.add_argument(
            "--yes",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Confirm requested operations without prompting",
        )

    def error(self, message):
        # Argparse messages can echo arbitrary argument values, including secrets.
        raise AgentboxError(f"Invalid arguments; see {self.prog} --help", code="invalid_arguments")

    def _get_value(self, action, arg_string):
        try:
            return super()._get_value(action, arg_string)
        except AgentboxError as exc:
            raise AgentboxError(str(exc), code="invalid_arguments") from None

    def print_help(self, file=None):
        raise HelpRequested(self.format_help())


def json_requested(arguments):
    # exec owns everything after its environment name, including flags.
    action = next((value for value in arguments if not value.startswith("-")), None)
    command_started = False
    for argument in arguments:
        if argument == "--":
            return False
        if argument == "--json":
            return True
        if action == "exec":
            if command_started and not argument.startswith("-"):
                return False
            if argument == "exec":
                command_started = True
    return False


def parser():
    cli = Parser(prog="abx")
    commands = cli.add_subparsers(dest="action", required=True)
    commands.add_parser("doctor")
    commands.add_parser("status")
    image = commands.add_parser("image", help="Manage local Dockerfile recipes and builds")
    image_ops = image.add_subparsers(dest="operation", required=True)
    image_ops.add_parser("ls")
    new = image_ops.add_parser("new")
    new.add_argument("name", type=config.name)
    new.add_argument("--template", choices=images.TEMPLATES, default="base")
    for operation in ("edit", "build", "inspect", "rm"):
        image_ops.add_parser(operation).add_argument("name", type=config.name)
    complete = commands.add_parser("completion", help="Print shell completion setup")
    complete.add_argument("shell", choices=["bash"], nargs="?", default="bash")
    complete.add_argument(
        "--names",
        choices=["environments", "projects", "configs", "images"],
        help=argparse.SUPPRESS,
    )
    validate = commands.add_parser("validate")
    validate.add_argument("config", help="YAML path or name from the user environment directory")
    project = commands.add_parser("project")
    operations = project.add_subparsers(dest="operation", required=True)
    operations.add_parser("list")
    add = operations.add_parser("add")
    add.add_argument("name", type=config.name)
    add.add_argument("--path", required=True)
    for operation in ("check", "repair", "revoke"):
        sub = operations.add_parser(operation)
        sub.add_argument("name", type=config.name)
    start = commands.add_parser("start", help="Start an environment from a YAML path or saved name")
    start.add_argument("config", help="YAML path or name from ~/.config/agentbox/environments")
    run = commands.add_parser("run", help="Run command in a temporary environment and remove it")
    run.add_argument("config", help="YAML path or saved environment configuration")
    proxy = commands.add_parser("proxy", help="Apply proxy rules or stop API access")
    proxy_ops = proxy.add_subparsers(dest="operation", required=True)
    proxy_ops.add_parser("build", help="Build the internal proxy component")
    apply = proxy_ops.add_parser("apply")
    apply.add_argument("config")
    for operation in ("stop", "rotate-ca"):
        operation_parser = proxy_ops.add_parser(operation)
        operation_parser.add_argument("name", type=config.name)
    for action in ("stop", "remove", "shell", "logs", "login-api-key", "exec"):
        sub = commands.add_parser(action)
        sub.add_argument("name", type=config.name)
        if action == "logs":
            sub.add_argument("--proxy", action="store_true")
        if action == "exec":
            sub.add_argument("command", nargs=argparse.REMAINDER)
        if action == "login-api-key":
            sub.add_argument("--key-file", required=True)
    return cli


def main():
    global _output
    _output = Output(json_requested(sys.argv[1:]))
    try:
        args = parser().parse_args()
        if args.action == "completion":
            if args.names:
                if args.names not in ("configs", "images"):
                    settings = load_settings()
                    if os.getuid() != settings["operator_uid"]:
                        return
                print("\n".join(completion.names(args.names)))
            else:
                script = completion.bash_script()
                if _output.json_mode:
                    _output.finish(success(script))
                else:
                    print(script, end="")
            return
        if args.action == "validate":
            environment = config.load(args.config)
            _output.finish(success(environment.to_dict() if _output.json_mode else "OK"))
            return
        settings = load_settings()
        if os.getuid() != settings["operator_uid"]:
            raise AgentboxError("Run abx as the configured developer", code="permission_denied")
        if args.action == "image":
            if args.operation == "new":
                result = images.new(args.name, args.template)
            elif args.operation == "edit":
                code = images.edit(args.name, emit=_output.event if _output.json_mode else None)
                raise SystemExit(_output.finish(success(exit_code=code)))
            elif args.operation == "ls":
                names = images.names()
                result = rpc({"action": "image", "operation": "ls", "names": names})
                for name in names:
                    result[name]["path"] = str(images.recipe(name))
            else:
                path = images.recipe(args.name)
                request = {"action": "image", "operation": args.operation, "name": args.name}
                result = (
                    rpc(request, context=args.name) if args.operation == "build" else rpc(request)
                )
                result["path"] = str(path)
        elif args.action == "project":
            if args.operation == "add":
                result = project_update(settings, args.name, args.path)
            elif args.operation == "revoke":
                result = project_revoke(settings, args.name)
            else:
                entries = rpc({"action": "project", "operation": "list"})
                if args.operation == "list":
                    result = entries
                else:
                    entry = entries.get(args.name)
                    if not entry:
                        raise AgentboxError("Unknown project")
                    if args.operation == "repair":
                        rpc({"action": "project", "operation": "prepare-repair", "name": args.name})
                        result = project_update(settings, args.name, entry["path"])
                    else:
                        result = rpc({"action": "project", "operation": "check", "name": args.name})
                        result["operator_access_issues"] = projects.access_issues(
                            entry["path"], {settings["operator_uid"], settings["service_uid"]}
                        )
        elif args.action in ("start", "run") or (
            args.action == "proxy" and args.operation == "apply"
        ):
            environment = config.load(args.config)
            if args.action in ("start", "run"):
                images.recipe(environment.image)
            payload = environment.to_dict()
            payload["network"] = {"allow": payload.pop("allow")}
            # Missing/invalid values are deliberately validated in the helper after apply stops
            # the old proxy. Never fail locally and leave old credentials active.
            tokens = {
                c.source_env: os.environ[c.source_env]
                for c in environment.credentials
                if c.source_env in os.environ
            }
            request = {"action": args.action, "config": payload, "tokens": tokens}
            if args.action == "run":
                request["tty"] = (
                    not _output.json_mode and sys.stdin.isatty() and sys.stdout.isatty()
                )
                raise SystemExit(_output.finish(rpc(request, stream=True)))
            if args.action == "proxy":
                request["operation"] = "apply"
            result = rpc(request)
            if args.action == "start" and not environment.persistent:
                _output.event(
                    "stderr", "abx: Non-persistent environment; shell or stop will remove it.\n"
                )
        elif args.action == "proxy":
            request = {"action": "proxy", "operation": args.operation}
            if hasattr(args, "name"):
                request["name"] = args.name
            result = rpc(request)
        elif args.action in ("shell", "exec"):
            command = getattr(args, "command", [])
            if command and command[0] == "--":
                command.pop(0)
            code = rpc(
                {
                    "action": args.action,
                    "name": args.name,
                    "command": command,
                    "tty": not _output.json_mode and sys.stdin.isatty() and sys.stdout.isatty(),
                },
                stream=True,
            )
            raise SystemExit(_output.finish(code))
        elif args.action == "login-api-key":
            path = Path(args.key_file)
            metadata = path.stat()
            if metadata.st_uid != os.getuid() or metadata.st_mode & 0o077:
                raise AgentboxError("Key file must be private to the developer (mode 0600)")
            result = rpc(
                {"action": args.action, "name": args.name, "key": path.read_text().strip()}
            )
        else:
            request = {"action": args.action}
            if hasattr(args, "name"):
                request["name"] = args.name
            if hasattr(args, "proxy"):
                request["proxy"] = args.proxy
            result = rpc(request)
            if args.action == "logs":
                _output.event("stdout", result)
                raise SystemExit(_output.finish(success(exit_code=0)))
        table = args.action == "status" or (
            args.action in ("project", "image") and args.operation in ("list", "ls")
        )
        _output.finish(success(result), table=args.action if table else False)
    except HelpRequested as exc:
        if _output.json_mode:
            _output.finish(success({"help": exc.text}))
        else:
            print(exc.text, end="")
    except KeyboardInterrupt:
        raise SystemExit(
            _output.finish(failure("interrupted", "Interrupted", exit_code=130))
        ) from None
    except (AgentboxError, OSError, ValueError, subprocess.SubprocessError) as exc:
        code = exc.code if isinstance(exc, AgentboxError) else "operation_failed"
        message = str(exc) if isinstance(exc, AgentboxError) else type(exc).__name__
        details = exc.details if isinstance(exc, AgentboxError) else None
        raise SystemExit(_output.finish(failure(code, message, details=details))) from None


def control_main():
    try:
        settings = load_settings()
        if os.getuid() != settings["service_uid"] or os.environ.get("SUDO_UID") != str(
            settings["operator_uid"]
        ):
            raise AgentboxError(
                "Control entry point requires the configured sudo caller and service user",
                code="permission_denied",
            )
        source = getattr(sys.stdin, "buffer", sys.stdin)
        source = getattr(source, "raw", source)
        raw = source.readline(1048577)
        if len(raw) > 1048576:
            raise AgentboxError("Control request too large", code="invalid_request")
        request = json.loads(raw)
        if not isinstance(request, dict) or not isinstance(request.get("action"), str):
            raise AgentboxError("Expected a structured control operation", code="invalid_request")
        control = Control(settings)
        streaming = request["action"] in ("exec", "run", "shell")
        if streaming:
            control.docker.input_source = source
            control.docker.output = lambda stream, data: write_frame(
                {"type": "output", "stream": stream, "data": data}
            )
        if request.get("action") == "image" and request.get("operation") == "build":
            with tempfile.TemporaryFile() as context:
                shutil.copyfileobj(source, context)
                context.seek(0)
                result = control.dispatch(request, context=context)
        else:
            if not streaming:
                rest = source.read(1048577 - len(raw))
                if len(raw) + len(rest) > 1048576 or rest.strip():
                    raise AgentboxError("Unexpected trailing control input", code="invalid_request")
            result = control.dispatch(request)
        write_frame(success(exit_code=result) if streaming else success(result))
    except (AgentboxError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, AgentboxError) else type(exc).__name__
        code = exc.code if isinstance(exc, AgentboxError) else "control_failed"
        write_frame(failure(code, message, details=getattr(exc, "details", None)))
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        write_frame(failure("interrupted", "Interrupted", exit_code=130))
        raise SystemExit(130) from None
