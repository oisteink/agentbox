import os

import pytest

from agentbox import mounts, uninstall
from agentbox.errors import AgentboxError
from agentbox.mounts import grant_acl, named_acl, scan


def test_regular_files_do_not_gain_execute():
    acl = "user::rw-\ngroup::r--\nother::r--\n"
    result = grant_acl(acl, 1001, 1000, False)
    assert "user:1001:rw-" in result
    assert "user:1000:rw-" in result
    assert "mask::rw-" in result


def test_latent_group_permissions_are_not_silently_enabled():
    acl = "user::rwx\nuser:2000:rwx\ngroup::rwx\nmask::r--\nother::---\n"
    repaired = grant_acl(acl, 1001, 1000, True)
    assert "group::r--" in repaired
    assert "user:2000:r--" in repaired
    assert "mask::rwx" in repaired


def test_revocation_keeps_mask_and_other_entries():
    acl = "user::rwx\nuser:1001:rwx\ngroup::r-x\nmask::rwx\nother::r-x\n"
    result = named_acl(acl, 1001, "---")
    assert "user:1001:---" in result
    assert "group::r-x" in result
    assert "mask::rwx" in result


def test_traversal_sets_an_effective_mask():
    result = named_acl("user::rwx\ngroup::---\nother::---\n", 1001, "--x")
    assert "mask::--x" in result


def test_hardlink_rejected_before_any_changes(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    original = tmp_path / "outside"
    original.write_text("unchanged")
    original.chmod(0o640)
    (mount / "inside").hardlink_to(original)
    before = original.stat()
    with pytest.raises(AgentboxError, match="Hard-linked"):
        scan(mount, {os.getuid()})
    assert original.stat().st_mode == before.st_mode
    assert original.read_text() == "unchanged"


def test_mount_symlink_is_not_followed(tmp_path):
    mount = tmp_path / "mount"
    mount.mkdir()
    (mount / "outside").symlink_to(tmp_path)
    nodes = scan(mount, {os.getuid()})
    assert len(nodes) == 1


@pytest.mark.parametrize("scanner", ["mount", "uninstall"])
def test_nested_mount_is_skipped_without_opening_it(tmp_path, monkeypatch, scanner):
    root = tmp_path / "mount"
    root.mkdir()
    (root / "file").write_text("selected code")
    nested = root / "nested"
    nested.mkdir()
    monkeypatch.setattr(mounts, "_mounts", lambda: {str(nested)})
    actual_open = os.open

    def inaccessible_mount(path, flags, *args, **kwargs):
        # Simulate a private mounted directory even when tests run as root.
        if path == "nested":
            raise PermissionError("nested mount is not accessible to the service user")
        return actual_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(mounts.os, "open", inaccessible_mount)
    nodes = scan(root, {os.getuid()}) if scanner == "mount" else uninstall.inspect_tree(root)
    assert {node["relative"] for node in nodes} == {".", "file"}


def test_repair_grants_owner_bits_without_relying_on_named_owner_entry():
    result = grant_acl("user::r--\ngroup::---\nother::---\n", 1001, 1000, False)
    assert "user::rw-\n" in result
    assert "other::---\n" in result and "group::---\n" in result
