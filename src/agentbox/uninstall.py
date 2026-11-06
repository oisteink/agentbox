"""Administrator-only uninstall with bounded mount ownership and ACL cleanup."""

import argparse
import ctypes
import fcntl
import grp
import json
import os
import pwd
import shutil
import stat
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from . import mounts
from .errors import AgentboxError
from .settings import load_settings

HOME = Path("/var/lib/agentbox")
JOURNAL = Path("/var/lib/agentbox-operator")
FIXED_DIRECTORIES = (Path("/opt/agentbox"), Path("/etc/agentbox"), HOME, JOURNAL)
FIXED_FILES = (
    Path("/etc/sudoers.d/agentbox"),
    Path("/etc/systemd/user/agentbox-watch.service"),
    Path("/usr/local/bin/abx"),
    Path("/usr/local/bin/agentbox"),
    Path("/usr/local/libexec/agentbox-control"),
    Path("/usr/local/libexec/agentbox-watch"),
    Path("/usr/local/share/bash-completion/completions/abx"),
    Path("/usr/local/share/bash-completion/completions/agentbox"),
)


def run(*args, accepted=(0,), **kwargs):
    result = subprocess.run(
        args, capture_output=True, text=True, timeout=120, check=False, **kwargs
    )
    if result.returncode not in accepted:
        raise AgentboxError(f"{args[0]} failed: {result.stderr.strip()}")
    return result.stdout


def private_directory(path, uid):
    meta = path.lstat()
    if not stat.S_ISDIR(meta.st_mode) or meta.st_uid != uid or meta.st_mode & 0o077:
        raise AgentboxError(f"Unexpected owner, permissions or directory type: {path}")


def read_json_at(directory, filename, uid):
    """Read a bounded regular state file without following a final symlink."""
    try:
        parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return {}
    try:
        try:
            fd = os.open(filename, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            return {}
        with os.fdopen(fd) as source:
            meta = os.fstat(source.fileno())
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != uid or meta.st_mode & 0o077:
                raise AgentboxError(f"Unexpected state file: {directory / filename}")
            text = source.read(16_777_217)
            if len(text) > 16_777_216:
                raise AgentboxError("State file is too large")
            value = json.loads(text)
            if not isinstance(value, dict):
                raise AgentboxError("Invalid state document")
            return value
    finally:
        os.close(parent)


@contextmanager
def state_lock(directory, uid, dry_run=False):
    if not directory.exists():
        if dry_run:
            yield
            return
        directory.mkdir(mode=0o700)
        os.chown(directory, uid, -1)
    private_directory(directory, uid)
    parent = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            fd = os.open("lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        except FileNotFoundError:
            if dry_run:
                yield
                return
            try:
                fd = os.open(
                    "lock",
                    os.O_RDONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                    dir_fd=parent,
                )
                os.fchown(fd, uid, -1)
            except FileExistsError:
                fd = os.open("lock", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        try:
            meta = os.fstat(fd)
            if not stat.S_ISREG(meta.st_mode) or meta.st_uid != uid:
                raise AgentboxError("Unexpected state lock")
            fcntl.flock(fd, fcntl.LOCK_SH if dry_run else fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)
    finally:
        os.close(parent)


def transfer_owner(fd, uid, gid):
    # AT_EMPTY_PATH works with O_PATH descriptors, including symlinks themselves.
    library = ctypes.CDLL(None, use_errno=True)
    call = library.fchownat
    call.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_int]
    call.restype = ctypes.c_int
    if call(fd, b"", uid, gid, 0x1000 | 0x100):
        raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))


def inspect_tree(root):
    """Pin each node's identity, skip nested mounts and never follow symlinks."""
    nested = mounts._mounts() - {str(root)}
    nodes = []

    def walk(fd, relative):
        meta = os.fstat(fd)
        if str(root / relative) in nested:
            return
        directory = stat.S_ISDIR(meta.st_mode)
        nodes.append(
            {
                "relative": str(relative),
                "device": meta.st_dev,
                "inode": meta.st_ino,
                "uid": meta.st_uid,
                "directory": directory,
                "symlink": stat.S_ISLNK(meta.st_mode),
            }
        )
        if directory:
            for entry in os.scandir(fd):
                if str(root / relative / entry.name) in nested:
                    continue
                flags = (
                    os.O_RDONLY | os.O_DIRECTORY
                    if entry.is_dir(follow_symlinks=False)
                    else os.O_PATH
                )
                child = os.open(entry.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
                try:
                    walk(child, relative / entry.name)
                finally:
                    os.close(child)

    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        walk(fd, Path("."))
    finally:
        os.close(fd)
    return nodes


@contextmanager
def open_node(root, node):
    current = os.open(root, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        relative = Path(node["relative"])
        if relative.is_absolute() or ".." in relative.parts:
            raise AgentboxError("Invalid mount-relative path")
        for index, part in enumerate(relative.parts):
            flags = os.O_PATH | os.O_NOFOLLOW
            if index < len(relative.parts) - 1:
                flags |= os.O_DIRECTORY
            following = os.open(part, flags, dir_fd=current)
            os.close(current)
            current = following
        meta = os.fstat(current)
        if (meta.st_dev, meta.st_ino, meta.st_uid) != (node["device"], node["inode"], node["uid"]):
            raise AgentboxError("Mount changed during uninstall; rerun uninstall")
        yield current
    finally:
        os.close(current)


def prepare_mounts(entries, operator_uid, service_uid):
    prepared = []
    for entry in entries.values():
        if entry["type"] == "volume":
            continue
        if entry["type"] != "directory":
            raise AgentboxError("Unknown registered mount type")
        try:
            root = mounts.validate_root(entry["path"], operator_uid)
        except FileNotFoundError:
            if entry.get("status") != "revoked":
                raise AgentboxError(f"Registered mount is missing: {entry['path']}") from None
            print(f"Skipping removed, revoked mount: {entry['path']}", flush=True)
            continue
        if str(root) != entry["path"] or mounts.identity(root) != entry["identity"]:
            raise AgentboxError(f"Registered mount root changed: {entry['path']}")
        nodes = inspect_tree(root)
        for node in nodes:
            with open_node(root, node) as fd:
                if node["symlink"]:
                    continue
                acl = mounts.read_acl(fd)
                changed_acl = mounts.remove_service_acl(acl, service_uid)
                meta = os.fstat(fd)
                if (
                    stat.S_ISREG(meta.st_mode)
                    and meta.st_nlink != 1
                    and (node["uid"] == service_uid or changed_acl != acl)
                ):
                    raise AgentboxError(
                        f"Hard-linked shared file requires manual cleanup: {root / node['relative']}"
                    )
        prepared.append((root, nodes))
    return prepared


def clean_mounts(prepared, service_uid, operator_uid, operator_gid):
    transferred = 0
    for root, nodes in prepared:
        for node in reversed(nodes):
            with open_node(root, node) as fd:
                meta = os.fstat(fd)
                if not node["symlink"]:
                    before = mounts.read_acl(fd)
                    after = mounts.remove_service_acl(before, service_uid)
                    if (
                        stat.S_ISREG(meta.st_mode)
                        and meta.st_nlink != 1
                        and (meta.st_uid == service_uid or after != before)
                    ):
                        raise AgentboxError("Hard link appeared during uninstall")
                    if after != before:
                        mounts.write_acl(fd, after)
                if meta.st_uid == service_uid:
                    transfer_owner(fd, operator_uid, operator_gid)
                    transferred += 1
    return transferred


def clean_parents(journal, roots, service_uid, operator_uid):
    for path, record in journal.get("parents", {}).items():
        parent = Path(path)
        if not any(parent in root.parents for root in roots):
            raise AgentboxError("ACL journal contains an unrelated ancestor")
        try:
            fd = os.open(parent, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
        except FileNotFoundError:
            continue  # Deleted ancestor has no remaining ACL to restore.
        try:
            meta = os.fstat(fd)
            identity = {"device": meta.st_dev, "inode": meta.st_ino, "uid": meta.st_uid}
            if meta.st_uid != operator_uid or identity != record["identity"]:
                raise AgentboxError(f"Ancestor identity changed: {parent}")
            current = mounts.read_acl(fd)
            after = record.get("after")
            # Restore our snapshot only when untouched; otherwise preserve manual edits.
            desired = (
                record["before"]
                if current == after
                else mounts.remove_service_acl(current, service_uid)
            )
            mounts.write_acl(fd, mounts.remove_service_acl(desired, service_uid))
        finally:
            os.close(fd)


def validate_installation(settings):
    service = pwd.getpwnam("agentbox")
    operator = pwd.getpwuid(settings["operator_uid"])
    if (
        service.pw_uid == 0
        or operator.pw_uid in (0, service.pw_uid)
        or service.pw_uid != settings["service_uid"]
        or service.pw_dir != str(HOME)
        or settings["home"] != str(HOME)
        or settings["operator_state"] != str(JOURNAL)
    ):
        raise AgentboxError("Unexpected installation identity or paths")
    private_directory(HOME, service.pw_uid)
    private_directory(JOURNAL, operator.pw_uid)
    for path in FIXED_DIRECTORIES:
        meta = path.lstat()
        if not stat.S_ISDIR(meta.st_mode):
            raise AgentboxError(f"Refusing unexpected directory or symlink: {path}")
        if path in (Path("/opt/agentbox"), Path("/etc/agentbox")) and (
            meta.st_uid != 0 or meta.st_mode & 0o022
        ):
            raise AgentboxError(f"Installation directory is not administrator-owned: {path}")
    return service, operator


def stop_runtime(uid):
    # Disable new unprivileged control calls before stopping all service-user work.
    Path("/etc/sudoers.d/agentbox").unlink(missing_ok=True)
    run("/usr/bin/loginctl", "disable-linger", "agentbox")
    # Stop the dedicated user manager, including Docker and all its delegated cgroups.
    # This also works when its session bus is already unavailable.
    run("/usr/bin/systemctl", "stop", f"user@{uid}.service")
    run("/usr/bin/loginctl", "terminate-user", "agentbox", accepted=(0, 1))
    run("/usr/bin/pkill", "-KILL", "-u", str(uid), accepted=(0, 1))


def clear_subids(uid):
    for path in (Path("/etc/subuid"), Path("/etc/subgid")):
        if path.exists():
            lines = path.read_text().splitlines(keepends=True)
            remaining = [
                line for line in lines if line.split(":", 1)[0] not in ("agentbox", str(uid))
            ]
            if lines != remaining:
                # userdel normally removes these; preserve unrelated entries and metadata.
                with path.open("w") as destination:
                    destination.writelines(remaining)


def uninstall(settings, dry_run=False):
    service, operator = validate_installation(settings)
    with (
        state_lock(JOURNAL, operator.pw_uid, dry_run),
        state_lock(HOME / "state", service.pw_uid, dry_run),
    ):
        data = read_json_at(HOME / "state", "state.json", service.pw_uid)
        journal = read_json_at(JOURNAL, "state.json", operator.pw_uid)
        if (data and data.get("schema") != 2) or (journal and journal.get("schema") != 2):
            raise AgentboxError("Unsupported or missing state; refusing destructive cleanup")
        if journal.get("mounts") and not data.get("mounts"):
            raise AgentboxError("Mount registry is missing; refusing to lose ownership information")
        entries = data.get("mounts", {})
        environments = data.get("environments", {})
        print(
            f"Warning: all Agentbox environments will be stopped ({len(environments)} registered).",
            flush=True,
        )
        print(
            "Container homes, credentials, volumes, images and Agentbox data will be deleted.",
            flush=True,
        )
        print(f"Agentbox-owned mount files will be transferred to {operator.pw_name}.", flush=True)
        if dry_run:
            prepared = prepare_mounts(entries, operator.pw_uid, service.pw_uid)
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "directories": [str(root) for root, _ in prepared],
                        "volumes": [
                            entry["volume"]
                            for entry in entries.values()
                            if entry["type"] == "volume"
                        ],
                        "remove": [str(path) for path in (*FIXED_FILES, *FIXED_DIRECTORIES)],
                    },
                    indent=2,
                )
            )
            return
        stop_runtime(service.pw_uid)
        prepared = prepare_mounts(entries, operator.pw_uid, service.pw_uid)
        transferred = clean_mounts(prepared, service.pw_uid, operator.pw_uid, operator.pw_gid)
        clean_parents(
            journal,
            [Path(entry["path"]) for entry in entries.values() if entry["type"] == "directory"],
            service.pw_uid,
            operator.pw_uid,
        )
        mountpoints = mounts._mounts()
        for path in FIXED_DIRECTORIES:
            if any(Path(mount) == path or path in Path(mount).parents for mount in mountpoints):
                raise AgentboxError(f"Mount remains under {path}; refusing directory removal")
        # Recheck fixed directory identities before deletion; never follow top-level links.
        validate_installation(settings)
        run("/usr/sbin/userdel", "agentbox")
        try:
            group = grp.getgrnam("agentbox")
        except KeyError:
            pass
        else:
            if (
                group.gr_gid != operator.pw_gid
                and not group.gr_mem
                and not any(user.pw_gid == group.gr_gid for user in pwd.getpwall())
            ):
                run("/usr/sbin/groupdel", "agentbox")
        clear_subids(service.pw_uid)
        dropin = Path(f"/etc/systemd/system/user@{service.pw_uid}.service.d/agentbox.conf")
        dropin.unlink(missing_ok=True)
        try:
            dropin.parent.rmdir()
        except OSError:
            pass  # Preserve other administrator drop-ins.
        for path in FIXED_FILES:
            path.unlink(missing_ok=True)
        for path in FIXED_DIRECTORIES:
            shutil.rmtree(path)
        run("/usr/bin/systemctl", "daemon-reload")
        print(
            f"Agentbox removed. Transferred {transferred} mount entries to {operator.pw_name}.",
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(prog="scripts/uninstall.sh")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show cleanup without changing files or services"
    )
    args = parser.parse_args()
    try:
        if os.getuid() != 0:
            raise AgentboxError("Uninstall requires administrator privileges")
        uninstall(load_settings(), args.dry_run)
    except (AgentboxError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"uninstall: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
