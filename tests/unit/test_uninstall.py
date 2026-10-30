import os
import stat

import pytest

from agentbox import projects, uninstall
from agentbox.errors import AgentboxError


def test_acl_cleanup_preserves_other_entries_and_masks():
    before = (
        "user::rwx\nuser:123:rwx\nuser:456:r--\ngroup::r-x\nmask::r-x\nother::---\n"
        "default:user::rwx\ndefault:user:123:rwx\ndefault:user:456:r--\n"
        "default:group::r-x\ndefault:mask::r-x\ndefault:other::---\n"
    )
    result = uninstall.remove_service_acl(before, 123)
    assert "user:123:" not in result
    assert result == before.replace("default:user:123:rwx\n", "").replace("user:123:rwx\n", "")


def test_tree_scan_does_not_follow_links_or_nested_mounts(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "file").write_text("code")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").touch()
    (root / "link").symlink_to(outside, target_is_directory=True)
    nested = root / "mount"
    nested.mkdir()
    (nested / "hidden").touch()
    monkeypatch.setattr(projects, "_mounts", lambda: {str(nested)})
    nodes = uninstall.inspect_tree(root)
    assert {node["relative"] for node in nodes} == {".", "file", "link"}
    assert next(node for node in nodes if node["relative"] == "link")["symlink"]


def test_open_node_rejects_replaced_file(tmp_path):
    (tmp_path / "file").touch()
    nodes = uninstall.inspect_tree(tmp_path)
    node = next(node for node in nodes if node["relative"] == "file")
    (tmp_path / "file").rename(tmp_path / "old-file")
    (tmp_path / "file").touch()
    with pytest.raises(AgentboxError, match="Project changed"):
        with uninstall.open_node(tmp_path, node):
            pytest.fail("Replaced file was accepted")


def test_affected_hardlink_refused_before_cleanup(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("keep")
    os.link(outside, root / "shared")
    entries = {"project": {"path": str(root), "identity": projects.identity(root)}}
    with pytest.raises(AgentboxError, match="Hard-linked shared file"):
        uninstall.prepare_projects(entries, os.getuid(), os.getuid())
    assert outside.read_text() == "keep"


def test_symlink_cleanup_transfers_link_without_changing_target(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.write_text("keep")
    link = root / "link"
    link.symlink_to(outside)
    nodes = uninstall.inspect_tree(root)
    transferred = []
    monkeypatch.setattr(
        uninstall, "transfer_owner", lambda fd, uid, gid: transferred.append(os.fstat(fd))
    )
    uninstall.clean_projects([(root, nodes)], os.getuid(), 99999, 99999)
    assert any(stat.S_ISLNK(meta.st_mode) for meta in transferred)
    assert outside.read_text() == "keep"
    assert link.is_symlink()


def test_transfer_owner_uses_pinned_fd(tmp_path):
    target = tmp_path / "file"
    target.touch()
    fd = os.open(target, os.O_PATH | os.O_NOFOLLOW)
    try:
        uninstall.transfer_owner(fd, os.getuid(), os.getgid())
        assert os.fstat(fd).st_uid == os.getuid()
    finally:
        os.close(fd)


def test_state_symlink_is_refused(tmp_path):
    target = tmp_path / "actual.json"
    target.write_text("{}")
    (tmp_path / "state.json").symlink_to(target)
    with pytest.raises(OSError):
        uninstall.read_json_at(tmp_path, "state.json", os.getuid())


def test_dry_run_lock_does_not_create_directory_or_file(tmp_path):
    missing = tmp_path / "state"
    with uninstall.state_lock(missing, os.getuid(), dry_run=True):
        assert not missing.exists()
    missing.mkdir(mode=0o700)
    with uninstall.state_lock(missing, os.getuid(), dry_run=True):
        assert not (missing / "lock").exists()


def test_parent_cleanup_preserves_manual_acl_changes(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    fd = os.open(tmp_path, os.O_PATH | os.O_DIRECTORY)
    try:
        before = "user::rwx\ngroup::---\nother::---\n"
        current = projects.named_acl(projects.named_acl(before, 12345, "--x"), 12346, "r--")
        written = []
        monkeypatch.setattr(projects, "read_acl", lambda fd: current)
        monkeypatch.setattr(projects, "write_acl", lambda fd, acl: written.append(acl))
        journal = {
            "parents": {
                str(tmp_path): {
                    "before": before,
                    "after": projects.named_acl(before, 12345, "--x"),
                    "identity": projects.identity(tmp_path),
                }
            }
        }
        uninstall.clean_parents(journal, [root], 12345, os.getuid())
        assert written == [uninstall.remove_service_acl(current, 12345)]
    finally:
        os.close(fd)
