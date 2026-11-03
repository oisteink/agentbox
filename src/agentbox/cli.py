"""Developer CLI and service-user entry point; control requests travel over stdin."""

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path

from . import completion, config, images, projects
from .control import Control
from .errors import AgentboxError
from .settings import load_settings
from .state import Store, atomic_json


def rpc(request, stream=False, context=None):
    command = ["/usr/bin/sudo", "-H", "-u", "agentbox", "/usr/local/libexec/agentbox-control"]
    if stream and request.get("action") == "run":
        process = subprocess.Popen(command, stdin=subprocess.PIPE, text=True)
        try:
            process.communicate(json.dumps(request))
        except KeyboardInterrupt:
            process.send_signal(signal.SIGINT)
            while True:
                try:
                    process.wait()
                    break
                except KeyboardInterrupt:
                    pass  # Let the helper finish cleanup before returning.
        return process.returncode
    options = {"text": True, "capture_output": not stream, "check": False}
    if context is None:
        completed = subprocess.run(command, input=json.dumps(request), **options)
    else:
        with tempfile.TemporaryFile() as source:
            source.write((json.dumps(request) + "\n").encode())
            images.archive(context, source)
            source.seek(0)
            completed = subprocess.run(command, stdin=source, **options)
    if stream:
        return completed.returncode
    if completed.returncode:
        raise AgentboxError((completed.stderr or "Control request failed").strip())
    return json.loads(completed.stdout)


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


def parser():
    cli = argparse.ArgumentParser(prog="abx")
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
                print(completion.bash_script(), end="")
            return
        if args.action == "validate":
            print(json.dumps(config.load(args.config).to_dict(), indent=2))
            return
        settings = load_settings()
        if os.getuid() != settings["operator_uid"]:
            raise AgentboxError("Run abx as the configured developer")
        if args.action == "image":
            if args.operation == "new":
                result = images.new(args.name, args.template)
            elif args.operation == "edit":
                raise SystemExit(images.edit(args.name))
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
                request["tty"] = sys.stdin.isatty() and sys.stdout.isatty()
                raise SystemExit(rpc(request, stream=True))
            if args.action == "proxy":
                request["operation"] = "apply"
            result = rpc(request)
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
                    "action": "exec",
                    "name": args.name,
                    "command": command,
                    "tty": sys.stdin.isatty() and sys.stdout.isatty(),
                },
                stream=True,
            )
            raise SystemExit(code)
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
        print(result if isinstance(result, str) else json.dumps(result, indent=2))
    except (AgentboxError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"abx: {exc}", file=sys.stderr)
        raise SystemExit(2) from None


def control_main():
    try:
        settings = load_settings()
        if os.getuid() != settings["service_uid"] or os.environ.get("SUDO_UID") != str(
            settings["operator_uid"]
        ):
            raise AgentboxError(
                "Control entry point requires the configured sudo caller and service user"
            )
        # Read the header and tar through the same buffer to preserve prefetched bytes.
        source = getattr(sys.stdin, "buffer", sys.stdin)
        raw = source.readline(1048577)
        if len(raw) > 1048576:
            raise AgentboxError("Control request too large")
        request = json.loads(raw)
        if not isinstance(request, dict) or not isinstance(request.get("action"), str):
            raise AgentboxError("Expected a structured control operation")
        if request.get("action") == "image" and request.get("operation") == "build":
            with tempfile.TemporaryFile() as context:
                shutil.copyfileobj(source, context)
                context.seek(0)
                result = Control(settings).dispatch(request, context=context)
        else:
            rest = source.read(1048577 - len(raw))
            if len(raw) + len(rest) > 1048576:
                raise AgentboxError("Control request too large")
            if rest.strip():
                raise AgentboxError("Unexpected trailing control input")
            result = Control(settings).dispatch(request)
        if request.get("action") in ("exec", "run"):
            raise SystemExit(result)
        print(json.dumps(result))
    except (AgentboxError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        # Never print the request, argv, subprocess exception or key material.
        message = str(exc) if isinstance(exc, AgentboxError) else type(exc).__name__
        print(f"agentbox control: {message}", file=sys.stderr)
        raise SystemExit(2) from None
    except KeyboardInterrupt:
        raise SystemExit(130) from None
