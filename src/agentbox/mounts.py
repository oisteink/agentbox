"""Unprivileged ACL operations. Never change owners or follow mount symlinks."""

import os
import pwd
import re
import stat
import subprocess
from contextlib import contextmanager
from pathlib import Path

from .errors import AgentboxError


def _command(args, *, fd, source=None):
    completed = subprocess.run(
        args, input=source, capture_output=True, text=True, pass_fds=(fd,), check=False
    )
    if completed.returncode:
        raise AgentboxError(f"ACL operation failed: {completed.stderr.strip()}")
    return completed.stdout


def read_acl(fd):
    return _command(["/usr/bin/getfacl", "-cpn", "--", f"/proc/self/fd/{fd}"], fd=fd)


def write_acl(fd, content):
    _command(
        ["/usr/bin/setfacl", "--no-mask", "--set-file=-", "--", f"/proc/self/fd/{fd}"],
        fd=fd,
        source=content,
    )


def _bits(text):
    return sum(bit for char, bit in zip(text, (4, 2, 1), strict=True) if char != "-")


def _permissions(bits):
    return "".join(char if bits & bit else "-" for char, bit in zip("rwx", (4, 2, 1), strict=True))


def grant_acl(original, service_uid, operator_uid, directory, executable=False):
    entries = {}
    for line in original.splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            key, permissions = line.rsplit(":", 1)
            entries[key] = _bits(permissions)
    wanted = 7 if directory or executable else 6
    for prefix in ["", "default:"] if directory else [""]:
        if prefix and not any(k.startswith(prefix) for k in entries):
            entries.update({prefix + key: entries[key] for key in ("user:", "group:", "other:")})
        old_mask = entries.get(prefix + "mask:", entries[prefix + "group:"])
        new_mask = old_mask | wanted
        for key, bits in entries.items():
            if key.startswith("default:") != bool(prefix):
                continue
            local = key.removeprefix(prefix)
            if local in (f"user:{service_uid}", f"user:{operator_uid}", "user:", "other:", "mask:"):
                continue
            if bits & new_mask != bits & old_mask:
                # One shared ACL mask covers every named user/group. Preserve
                # unrelated effective rights before widening it for the two
                # collaborating users, rather than reviving masked permissions.
                entries[key] = bits & old_mask
        # The owner entry takes precedence over a named entry for the same UID.
        # Every scanned owner is one of the two explicitly authorized users.
        entries[prefix + "user:"] |= wanted
        entries[prefix + f"user:{service_uid}"] = wanted
        entries[prefix + f"user:{operator_uid}"] = wanted
        entries[prefix + "mask:"] = new_mask
    return "".join(f"{key}:{_permissions(bits)}\n" for key, bits in entries.items())


def named_acl(original, uid, permissions):
    lines = [line.split("#", 1)[0].strip() for line in original.splitlines() if line.strip()]
    lines = [line for line in lines if not line.startswith(f"user:{uid}:")]
    lines.append(f"user:{uid}:{permissions}")
    if not any(line.startswith("mask::") for line in lines):
        group = next(line.rsplit(":", 1)[1] for line in lines if line.startswith("group::"))
        lines.append("mask::" + group)
    for index, line in enumerate(lines):
        if line.startswith("mask::"):
            old_mask = _bits(line.rsplit(":", 1)[1])
            new_mask = old_mask | _bits(permissions)
            for other in lines:
                if other.startswith(("default:", "user::", "other::", "mask::", f"user:{uid}:")):
                    continue
                bits = _bits(other.rsplit(":", 1)[1])
                if bits & old_mask != bits & new_mask:
                    raise AgentboxError("Traversal grant would widen another ACL entry")
            lines[index] = "mask::" + _permissions(new_mask)
    return "\n".join(lines) + "\n"


def _mounts():
    paths = set()
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        encoded = line.split()[4]
        decoded = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m[1], 8)), encoded)
        paths.add(decoded)
    return paths


def scan(root, allowed_uids, skip_inaccessible=False):
    """Preflight a tree without crossing mounts, symlinks or unsafe file types."""
    root = Path(root)
    nested = _mounts() - {str(root)}
    nodes = []

    def walk(fd, relative):
        meta = os.fstat(fd)
        path = root / relative
        if str(path) in nested:
            return
        if meta.st_uid not in allowed_uids:
            raise AgentboxError(f"Unsupported owner on {path}")
        directory = stat.S_ISDIR(meta.st_mode)
        if not directory and not stat.S_ISREG(meta.st_mode):
            raise AgentboxError(f"Special files are not supported: {path}")
        if not directory and meta.st_nlink != 1:
            raise AgentboxError(f"Hard-linked files are not supported: {path}")
        nodes.append(
            {
                "relative": str(relative),
                "device": meta.st_dev,
                "inode": meta.st_ino,
                "uid": meta.st_uid,
                "directory": directory,
                "executable": bool(meta.st_mode & 0o111),
            }
        )
        if directory:
            for entry in os.scandir(fd):
                if str(root / relative / entry.name) in nested or entry.is_symlink():
                    continue
                flags = os.O_RDONLY if entry.is_dir(follow_symlinks=False) else os.O_PATH
                flags |= os.O_NOFOLLOW | os.O_NONBLOCK
                try:
                    child = os.open(entry.name, flags, dir_fd=fd)
                except PermissionError:
                    if skip_inaccessible:
                        continue
                    raise
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
def node_fd(root, node):
    current = os.open(root, os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        relative = Path(node["relative"])
        if relative.is_absolute() or ".." in relative.parts:
            raise AgentboxError("Invalid relative mount path")
        for part in relative.parts:
            following = os.open(part, os.O_PATH | os.O_NOFOLLOW, dir_fd=current)
            os.close(current)
            current = following
            if stat.S_ISLNK(os.fstat(current).st_mode):
                raise AgentboxError("Mount path changed into a symlink")
        meta = os.fstat(current)
        if (meta.st_dev, meta.st_ino, meta.st_uid) != (node["device"], node["inode"], node["uid"]):
            raise AgentboxError("Mount tree changed during ACL operation")
        if stat.S_ISREG(meta.st_mode) and meta.st_nlink != 1:
            raise AgentboxError("Hard link appeared during ACL operation")
        yield current
    finally:
        os.close(current)


def apply_owned(root, nodes, service_uid, operator_uid):
    changed = []
    try:
        for node in nodes:
            if node["uid"] != os.getuid():
                continue
            with node_fd(root, node) as fd:
                before = read_acl(fd)
                after = grant_acl(
                    before, service_uid, operator_uid, node["directory"], node["executable"]
                )
                write_acl(fd, after)
                changed.append((node, before))
    except (OSError, AgentboxError):
        for node, before in reversed(changed):
            try:
                with node_fd(root, node) as fd:
                    write_acl(fd, before)
            except (OSError, AgentboxError):
                pass  # Caller reports the operation as failed; explicit repair is required.
        raise


def fd_identity(fd):
    return _identity(os.fstat(fd))


def identity(path):
    return _identity(Path(path).stat())


def _identity(meta):
    return {"device": meta.st_dev, "inode": meta.st_ino, "uid": meta.st_uid}


def access_issues(root, allowed_uids):
    try:
        nodes = scan(root, allowed_uids)
        return [
            node["relative"]
            for node in nodes
            if not os.access(
                Path(root) / node["relative"],
                os.R_OK | os.W_OK | (os.X_OK if node["directory"] else 0),
            )
        ]
    except (OSError, AgentboxError):
        return ["Mount tree cannot be fully inspected; check permissions and supported file types"]


def validate_root(path, operator_uid):
    root = Path(path).resolve(strict=True)
    if (
        not root.is_dir()
        or root.stat().st_uid != operator_uid
        or "," in str(root)
        or any(ord(char) < 32 for char in str(root))
    ):
        raise AgentboxError("Mount root must be a directory owned by the developer, without commas")
    for forbidden in (
        "/var/lib/agentbox",
        "/var/lib/agentbox-operator",
        "/etc",
        "/run",
        "/proc",
        "/sys",
        "/dev",
        "/opt/agentbox",
    ):
        if root == Path(forbidden) or Path(forbidden) in root.parents:
            raise AgentboxError("Mount overlaps private or reserved host data")
    if root in (Path("/"), Path("/home"), Path(pwd.getpwuid(operator_uid).pw_dir)):
        raise AgentboxError("Register a mount directory, not an entire home")
    return root


def remove_service_acl(original, uid):
    """Remove the dedicated service identity, preserving masks and other entries."""
    return "".join(
        line + "\n"
        for line in original.splitlines()
        if not line.startswith((f"user:{uid}:", f"default:user:{uid}:"))
    )


def inventory(nodes):
    """Digest a complete scan; permissions can change without changing identity."""
    import hashlib
    import json

    keys = ("relative", "device", "inode", "uid", "directory")
    rows = [{key: node[key] for key in keys} for node in nodes]
    return hashlib.sha256(
        json.dumps(sorted(rows, key=lambda row: row["relative"]), sort_keys=True).encode()
    ).hexdigest()


def clean_owned(root, nodes, service_uid):
    for node in reversed(nodes):
        if node["uid"] == os.getuid():
            with node_fd(root, node) as fd:
                before = read_acl(fd)
                after = remove_service_acl(before, service_uid)
                if after != before:
                    write_acl(fd, after)
