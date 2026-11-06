"""Developer CLI and service-user entry point; control requests travel over stdin."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import replace
from pathlib import Path

from . import completion, config, images, mounts, sessions
from .control import Control
from .errors import AgentboxError
from .output import Output, confirm, failure, success, write_frame
from .process import pump
from .settings import load_settings
from .state import Store, atomic_json

_output = Output()


class StreamResult(dict):
    def __init__(self, result, *, input_ready=False, interrupted=False):
        super().__init__(result)
        self.input_ready = input_ready
        self.interrupted = interrupted


def rpc(request, stream=False, context=None):
    command = ["/usr/bin/sudo", "-H", "-u", "agentbox", "/usr/local/libexec/agentbox-control"]
    frames = []
    buffer = ""
    invalid = False
    ready = False

    def receive(channel, text):
        nonlocal buffer, invalid, ready
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
                elif frame == {"type": "input_ready"} and stream and not ready:
                    ready = True
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
        status = pump(
            child,
            receive,
            prefix=header if context is None else b"",
            source=sys.stdin.buffer if stream and not request.get("tty") else None,
            input_ready=lambda: ready,
        )
    if status == 130:
        if stream:
            return StreamResult(
                failure("interrupted", "Interrupted", exit_code=130),
                input_ready=ready,
                interrupted=True,
            )
        raise KeyboardInterrupt
    if invalid or buffer or len(frames) != 1:
        raise AgentboxError(
            "Control helper did not return a complete result", code="control_protocol_error"
        )
    result = frames[0]
    if stream:
        return StreamResult(result, input_ready=ready)
    if not result["ok"]:
        error = result["error"]
        raise AgentboxError(error["message"], code=error["code"], details=error.get("details"))
    return result.get("data")


def _fd(path):
    return os.open(path, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)


def _mount_root(settings, entry):
    root = mounts.validate_root(entry["path"], settings["operator_uid"])
    if mounts.identity(root) != entry["identity"]:
        raise AgentboxError("Mount root identity changed", code="mount_identity_changed")
    return root


def mount_update(settings, name, source):
    root = mounts.validate_root(source, settings["operator_uid"])
    existing = rpc({"action": "mount", "operation": "list"}).get(name)
    if existing:
        if existing["status"] == "removing":
            raise AgentboxError(
                "Mount removal is incomplete; retry mount remove", code="mount_removing"
            )
        if (
            existing["type"] != "directory"
            or existing["path"] != str(root)
            or existing["identity"] != mounts.identity(root)
        ):
            raise AgentboxError(
                "Mount name is registered to a different source", code="mount_conflict"
            )
        if existing["status"] == "active":
            checked = mount_check(settings, name)
            if not checked["issues"]:
                return checked | {"changed": False}
    local = Store(settings["operator_state"])
    with local.locked() as journal:
        entry = rpc(
            {
                "action": "mount",
                "operation": "prepare",
                "name": name,
                "path": str(root),
                "identity": mounts.identity(root),
            }
        )
        journal.setdefault("parents", {})
        journal["mounts"][name] = {"path": str(root), "status": "adding"}
        atomic_json(local.root / "state.json", journal)
        _mount_attach_parents(settings, journal, local, name, root)
        _mount_grant_root(settings, root, entry["identity"])
        rpc(
            {
                "action": "mount",
                "operation": "prepare-repair",
                "name": name,
                "registration": entry["registration"],
            }
        )
        nodes = mounts.scan(root, {settings["operator_uid"], settings["service_uid"]})
        # Preflight all owned changes before touching descendant ACLs.
        for node in nodes:
            if node["uid"] == os.getuid():
                with mounts.node_fd(root, node) as fd:
                    mounts.grant_acl(
                        mounts.read_acl(fd),
                        settings["service_uid"],
                        settings["operator_uid"],
                        node["directory"],
                        node["executable"],
                    )
        mounts.apply_owned(root, nodes, settings["service_uid"], settings["operator_uid"])
        issues = mounts.access_issues(root, {settings["operator_uid"], settings["service_uid"]})
        if issues:
            raise AgentboxError(
                "Operator access remains incomplete: " + "; ".join(issues),
                code="mount_check_failed",
            )
        result = rpc(
            {
                "action": "mount",
                "operation": "finish",
                "name": name,
                "registration": entry["registration"],
            }
        )
        journal["mounts"][name]["status"] = "active"
        return result | {"changed": True}


def _mount_attach_parents(settings, journal, local, name, root):
    journal.setdefault("parents", {})
    for parent in reversed(root.parents):
        if parent.stat().st_uid != os.getuid():
            continue
        fd = _fd(parent)
        try:
            before = mounts.read_acl(fd)
            after = mounts.named_acl(before, settings["service_uid"], "--x")
            record = journal["parents"].setdefault(
                str(parent),
                {
                    "before": before,
                    "identity": mounts.identity(parent),
                    "mounts": [],
                },
            )
            if name not in record["mounts"]:
                record["mounts"].append(name)
            atomic_json(local.root / "state.json", journal)
            mounts.write_acl(fd, after)
            record["after"] = mounts.read_acl(fd)
            atomic_json(local.root / "state.json", journal)
        finally:
            os.close(fd)


def _mount_grant_root(settings, root, identity):
    fd = _fd(root)
    try:
        if mounts.fd_identity(fd) != identity:
            raise AgentboxError("Mount root identity changed", code="mount_identity_changed")
        mounts.write_acl(
            fd,
            mounts.grant_acl(
                mounts.read_acl(fd), settings["service_uid"], settings["operator_uid"], True
            ),
        )
    finally:
        os.close(fd)


def _mount_detach_parents(settings, journal, name):
    for path, record in list(journal.get("parents", {}).items()):
        if name not in record["mounts"]:
            continue
        remaining = [value for value in record["mounts"] if value != name]
        if remaining:
            record["mounts"] = remaining
            continue
        fd = _fd(path)
        try:
            if mounts.fd_identity(fd) != record["identity"]:
                raise AgentboxError("Ancestor identity changed; refusing ACL cleanup")
            current = mounts.read_acl(fd)
            desired = record["before"] if current == record.get("after") else current
            mounts.write_acl(fd, mounts.remove_service_acl(desired, settings["service_uid"]))
            del journal["parents"][path]
        finally:
            os.close(fd)


def mount_revoke(settings, name):
    local = Store(settings["operator_state"])
    with local.locked() as journal:
        entry = rpc({"action": "mount", "operation": "prepare-revoke", "name": name})
        if entry["active_users"]:
            _output.event(
                "stderr",
                "Warning: active mount users: "
                + ", ".join(entry["active_users"])
                + ". Existing mounts and open file handles can retain access; no environment is stopped.\n",
            )
        if entry["type"] == "directory":
            root = _mount_root(settings, entry)
            fd = _fd(root)
            try:
                mounts.write_acl(
                    fd, mounts.named_acl(mounts.read_acl(fd), settings["service_uid"], "---")
                )
            finally:
                os.close(fd)
            _mount_detach_parents(settings, journal, name)
            journal["mounts"].setdefault(name, {"path": str(root)})["status"] = "revoked"
            atomic_json(local.root / "state.json", journal)
        return rpc(
            {
                "action": "mount",
                "operation": "revoked",
                "name": name,
                "registration": entry["registration"],
            }
        ) | {
            "note": "Existing mounts/open handles may retain access; data and registration retained",
        }


def mount_check(settings, name, *, fix=False):
    entry = rpc({"action": "mount", "operation": "list"}).get(name)
    if not entry:
        raise AgentboxError("Unknown mount", code="mount_not_found")
    changed = False
    if fix:
        if entry["status"] == "removing":
            raise AgentboxError(
                "Mount removal is incomplete; retry mount remove", code="mount_removing"
            )
        before = mount_check(settings, name)
        if before["issues"]:
            if entry["status"] == "revoked":
                mount_revoke(settings, name)
            elif entry["type"] == "directory":
                mount_update(settings, name, entry["path"])
            else:
                return before | {"changed": False}
            changed = True
    result = rpc({"action": "mount", "operation": "check", "name": name})
    operator_issues = []
    if entry["type"] == "directory":
        try:
            root = _mount_root(settings, entry)
            operator_issues = mounts.access_issues(
                root, {settings["operator_uid"], settings["service_uid"]}
            )
        except (OSError, AgentboxError) as exc:
            operator_issues = [str(exc) if isinstance(exc, AgentboxError) else type(exc).__name__]
    result["operator_access_issues"] = operator_issues
    result["issues"] = result["service_access_issues"] + operator_issues
    return result | {"changed": changed}


def mount_remove(settings, name, *, yes=False):
    request = {"action": "mount", "operation": "prepare-remove", "name": name, "yes": yes}
    local = Store(settings["operator_state"])
    with local.locked() as journal:
        try:
            entry = rpc(request)
        except AgentboxError as exc:
            if exc.code != "confirmation_required" or _output.json_mode or not sys.stdin.isatty():
                raise
            confirm(str(exc), exc.details["affected"])
            entry = rpc(request | {"approval": exc.details["approval"]})
        if entry["type"] == "volume":
            return entry
        root = _mount_root(settings, entry)
        journal["mounts"][name] = {"path": str(root), "status": "removing"}
        atomic_json(local.root / "state.json", journal)
        _mount_attach_parents(settings, journal, local, name, root)
        _mount_grant_root(settings, root, entry["identity"])
        base = {"action": "mount", "name": name, "registration": entry["registration"]}
        rpc(base | {"operation": "prepare-clean"})
        nodes = mounts.scan(root, {settings["operator_uid"], settings["service_uid"]})
        digest = mounts.inventory(nodes)
        rpc(base | {"operation": "clean-owned", "inventory": digest})
        if (
            mounts.inventory(mounts.scan(root, {settings["operator_uid"], settings["service_uid"]}))
            != digest
        ):
            raise AgentboxError("Mount inventory changed during cleanup")
        mounts.clean_owned(root, nodes, settings["service_uid"])
        if (
            mounts.inventory(mounts.scan(root, {settings["operator_uid"], settings["service_uid"]}))
            != digest
        ):
            raise AgentboxError("Mount inventory changed during cleanup")
        _mount_detach_parents(settings, journal, name)
        del journal["mounts"][name]
        atomic_json(local.root / "state.json", journal)
        return rpc(base | {"operation": "forget", "inventory": digest})


def environment_request(environment, action):
    payload = environment.to_dict()
    payload["network"] = {"allow": payload.pop("allow")}
    tokens = {
        credential.source_env: os.environ[credential.source_env]
        for credential in environment.credentials
        if credential.source_env in os.environ
    }
    return {"action": action, "config": payload, "tokens": tokens}


def ensure_image(environment, *, temporary=False):
    digest = images.fingerprint(environment.image)
    entry = rpc({"action": "status"}).get(environment.name)
    if temporary and entry:
        raise AgentboxError(
            "Environment already exists; choose a new temporary name", code="environment_exists"
        )
    running = entry and entry.get("containers", {}).get("agent") == "running"
    built = rpc(
        {"action": "image", "operation": "inspect", "name": environment.image, "digest": digest}
    )
    if built["status"] != "built" and not running:
        _output.event("stderr", f"abx: Building image {environment.image}.\n")
        built = rpc(
            {"action": "image", "operation": "build", "name": environment.image, "if_needed": True},
            context=environment.image,
        )
        digest = built["digest"]
    return digest


def run_environment(environment, *, action="run", command=None, keep_running=False):
    if action == "run":
        environment = replace(
            environment,
            name=environment.name[:31] + "-run-" + uuid.uuid4().hex[:12],
            persistent=False,
        )
    request = environment_request(environment, action)
    request.update(
        tty=not _output.json_mode and sys.stdin.isatty() and sys.stdout.isatty(),
        client=sessions.identity(),
        keep_running=keep_running,
    )
    if action == "exec":
        request["command"] = command
    for attempt in range(3):
        digest = ensure_image(environment, temporary=action == "run")
        result = rpc(request | {"recipe_digest": digest}, stream=True)
        retry = (
            not result["ok"]
            and result["error"]["code"] == "image_outdated"
            and not getattr(result, "input_ready", False)
            and not getattr(result, "interrupted", False)
        )
        if not retry or attempt == 2:
            return result
    raise AssertionError("Unreachable session state")


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
    boundary = arguments.index("--") if "--" in arguments else len(arguments)
    return "--json" in arguments[:boundary]


def parser():
    cli = Parser(prog="abx")
    commands = cli.add_subparsers(dest="action", required=True)
    commands.add_parser("doctor")
    commands.add_parser("status")
    image = commands.add_parser("image", help="Manage local Dockerfile recipes and builds")
    image_ops = image.add_subparsers(dest="operation", required=True)
    image_ops.add_parser("list")
    new = image_ops.add_parser("new")
    new.add_argument("name", type=config.name)
    new.add_argument("--template", type=config.name, help="Local recipe or bundled template")
    for operation in ("edit", "build", "inspect", "remove"):
        image_ops.add_parser(operation).add_argument("name", type=config.name)
    complete = commands.add_parser("completion", help="Print shell completion setup")
    complete.add_argument("shell", choices=["bash"], nargs="?", default="bash")
    complete.add_argument(
        "--names",
        choices=["environments", "mounts", "configs", "images", "templates"],
        help=argparse.SUPPRESS,
    )
    validate = commands.add_parser("validate")
    validate.add_argument("config", help="YAML path or name from the user environment directory")
    mount = commands.add_parser("mount", help="Register directories and named Docker volumes")
    operations = mount.add_subparsers(dest="operation", required=True)
    operations.add_parser("list")
    add = operations.add_parser("add")
    add.add_argument("name", type=config.name)
    add.add_argument("path", nargs="?", help="Directory to register")
    add.add_argument("--volume", action="store_true", help="Create a named local Docker volume")
    for operation in ("check", "revoke", "remove"):
        help_text = (
            "Keep directory files after ACL cleanup; delete volume and its data"
            if operation == "remove"
            else None
        )
        sub = operations.add_parser(operation, help=help_text)
        sub.add_argument("name", type=config.name)
        if operation == "check":
            sub.add_argument("--fix", action="store_true")
    start = commands.add_parser("start", help="Start an environment from a YAML path or saved name")
    start.add_argument("config", help="YAML path or name from ~/.config/agentbox/environments")
    start.add_argument(
        "--keep-running", action="store_true", help="Keep the container until explicit stop"
    )
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
    for action in ("stop", "remove", "logs", "login-api-key", "exec"):
        sub = commands.add_parser(action)
        if action == "exec":
            sub.add_argument("config", help="YAML path or saved configuration name")
        else:
            sub.add_argument("name", type=config.name)
        if action == "logs":
            sub.add_argument("--proxy", action="store_true")
        if action == "exec":
            sub.add_argument("--keep-running", action="store_true")
            sub.add_argument("command", nargs="+")
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
                if args.names not in ("configs", "images", "templates"):
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
                result = images.edit(args.name, emit=_output.event if _output.json_mode else None)
                code = result.pop("exit_code")
                if not _output.json_mode:
                    _output.event(
                        "stderr",
                        f"abx: {args.name}: {'changed' if result['changed'] else 'unchanged'}.\n",
                    )
                raise SystemExit(_output.finish(success(result, exit_code=code)))
            elif args.operation == "list":
                names = images.names()
                result = rpc(
                    {
                        "action": "image",
                        "operation": "list",
                        "names": names,
                        "digests": {name: images.fingerprint(name) for name in names},
                    }
                )
                for name in names:
                    result[name]["path"] = str(images.recipe(name))
            else:
                path = images.recipe(args.name)
                request = {"action": "image", "operation": args.operation, "name": args.name}
                if args.operation == "inspect":
                    request["digest"] = images.fingerprint(args.name)
                result = (
                    rpc(request, context=args.name) if args.operation == "build" else rpc(request)
                )
                result["path"] = str(path)
        elif args.action == "mount":
            if args.operation == "add":
                if bool(args.path) == args.volume:
                    raise AgentboxError("Choose a directory or --volume", code="invalid_arguments")
                result = (
                    rpc({"action": "mount", "operation": "add-volume", "name": args.name})
                    if args.volume
                    else mount_update(settings, args.name, args.path)
                )
            elif args.operation == "revoke":
                result = mount_revoke(settings, args.name)
            elif args.operation == "remove":
                result = mount_remove(settings, args.name, yes=getattr(args, "yes", False))
            elif args.operation == "check":
                result = mount_check(settings, args.name, fix=args.fix)
                if result["issues"]:
                    raise AgentboxError(
                        "; ".join(result["issues"]), code="mount_check_failed", details=result
                    )
                if not _output.json_mode:
                    result = f"{args.name}: OK" + (" (repaired)" if result["changed"] else "")
            else:
                result = rpc({"action": "mount", "operation": "list"})
            if not _output.json_mode and args.operation in ("add", "revoke"):
                result = f"{args.name}: {'OK' if args.operation == 'add' else 'revoked'} ({result['type']})"
        elif args.action in ("start", "run", "exec"):
            environment = config.load(args.config)
            raise SystemExit(
                _output.finish(
                    run_environment(
                        environment,
                        action=args.action,
                        command=getattr(args, "command", None),
                        keep_running=getattr(args, "keep_running", False),
                    )
                )
            )
        elif args.action == "proxy" and args.operation == "apply":
            environment = config.load(args.config)
            result = rpc(environment_request(environment, "proxy") | {"operation": "apply"})
        elif args.action == "proxy":
            request = {"action": "proxy", "operation": args.operation}
            if hasattr(args, "name"):
                request["name"] = args.name
            result = rpc(request)
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
            args.action in ("mount", "image") and args.operation == "list"
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
        streaming = request["action"] in ("start", "exec", "run")
        if streaming:
            control.docker.input_source = source
            control.docker.ready = lambda: write_frame({"type": "input_ready"})
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
        write_frame(
            success({"name": request["config"]["name"]}, exit_code=result)
            if streaming
            else success(result)
        )
    except (AgentboxError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        message = str(exc) if isinstance(exc, AgentboxError) else type(exc).__name__
        code = exc.code if isinstance(exc, AgentboxError) else "control_failed"
        write_frame(failure(code, message, details=getattr(exc, "details", None)))
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        write_frame(failure("interrupted", "Interrupted", exit_code=130))
        raise SystemExit(130) from None
