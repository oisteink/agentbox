import os

import pytest

from agentbox.errors import AgentboxError
from agentbox.projects import grant_acl, named_acl, scan


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
    project = tmp_path / "project"
    project.mkdir()
    original = tmp_path / "outside"
    original.write_text("unchanged")
    original.chmod(0o640)
    (project / "inside").hardlink_to(original)
    before = original.stat()
    with pytest.raises(AgentboxError, match="Hard-linked"):
        scan(project, {os.getuid()})
    assert original.stat().st_mode == before.st_mode
    assert original.read_text() == "unchanged"


def test_project_symlink_is_not_followed(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    (project / "outside").symlink_to(tmp_path)
    nodes = scan(project, {os.getuid()})
    assert len(nodes) == 1
