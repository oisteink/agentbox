"""Mount identity, consent and interruption boundaries with real state files."""

import json
import os
from types import SimpleNamespace

import pytest

from agentbox import cli, mounts
from agentbox.control import Control
from agentbox.errors import AgentboxError
from agentbox.state import Store


@pytest.fixture
def volume_control(tmp_path, monkeypatch):
    control = Control(
        {"home": str(tmp_path), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    entry = {
        "type": "volume",
        "volume": "agentbox-mount-profile",
        "status": "active",
        "registration": "source-id",
    }
    volume = {
        "Driver": "local",
        "Options": {},
        "Labels": {
            "agentbox.installation": "installation",
            "agentbox.mount": "profile",
            "agentbox.registration": "source-id",
        },
    }
    mutations = []
    present = [volume]

    def run(*arguments):
        return SimpleNamespace(stdout=entry["volume"] + "\n" if present else "")

    def mutate(*arguments):
        mutations.append(arguments)
        present.clear()
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(control.docker, "run", run)
    monkeypatch.setattr(control.docker, "inspect", lambda *args: present[0])
    monkeypatch.setattr(control.docker, "mutate", mutate)
    monkeypatch.setattr(control, "mount_users", lambda *args, **kwargs: {})
    with control.store.locked() as data:
        data["installation"] = "installation"
        data["mounts"]["profile"] = entry
    return control, present, mutations


@pytest.mark.parametrize("change", ["source", "resources"])
def test_consent_cannot_apply_to_replaced_source_or_resources(volume_control, monkeypatch, change):
    control, _, mutations = volume_control
    users = {
        "environment": {
            "operation": "remove",
            "containers": ["agent", "proxy"],
            "networks": ["inside"],
        }
    }
    monkeypatch.setattr(control, "mount_users", lambda *args, **kwargs: users)
    with control.store.locked() as data:
        entry = data["mounts"]["profile"]
        with pytest.raises(AgentboxError) as error:
            control.remove_mount(data, "profile", entry, {})
        assert error.value.code == "confirmation_required"
        approval = error.value.details["approval"]
        assert entry["status"] == "active" and mutations == []
        if change == "source":
            entry["registration"] = "replacement"
        else:
            users = {"environment": dict(users["environment"], containers=["agent", "new-proxy"])}
        with pytest.raises(AgentboxError) as changed:
            control.remove_mount(data, "profile", entry, {"approval": approval})
        assert changed.value.code == "confirmation_required" and mutations == []
        assert entry["status"] == "active"


def test_retry_after_volume_deleted_before_registry_commit(volume_control, monkeypatch):
    control, present, mutations = volume_control
    save = control.save

    def interrupted_save(data):
        if "profile" not in data["mounts"]:
            raise KeyboardInterrupt
        save(data)

    monkeypatch.setattr(control, "save", interrupted_save)
    with pytest.raises(KeyboardInterrupt), control.store.locked() as data:
        control.mount(data, "prepare-remove", {"name": "profile"})
    assert not present and len(mutations) == 1
    assert (
        json.loads((control.store.root / "state.json").read_text())["mounts"]["profile"]["status"]
        == "removing"
    )
    monkeypatch.setattr(control, "save", save)
    with control.store.locked() as data:
        assert control.mount(data, "prepare-remove", {"name": "profile"})["data"] == "deleted"
        assert "profile" not in data["mounts"]
    assert len(mutations) == 1


def test_removing_refuses_a_foreign_replacement_volume(volume_control):
    control, present, mutations = volume_control
    present[0]["Labels"]["agentbox.registration"] = "foreign"
    with control.store.locked() as data:
        data["mounts"]["profile"]["status"] = "removing"
        with pytest.raises(AgentboxError, match="identity"):
            control.mount(data, "prepare-remove", {"name": "profile"})
        assert "profile" in data["mounts"] and not mutations


@pytest.mark.parametrize(
    "action", ["prepare", "add-volume", "prepare-repair", "prepare-revoke", "finish"]
)
def test_removing_cannot_be_reactivated(volume_control, action):
    control, _, mutations = volume_control
    with control.store.locked() as data:
        data["mounts"]["profile"]["status"] = "removing"
        with pytest.raises(AgentboxError) as error:
            control.mount(data, action, {"name": "profile"})
        assert error.value.code == "mount_removing" and not mutations


def test_incomplete_directory_inventory_cannot_be_forgotten(tmp_path, monkeypatch):
    control = Control(
        {"home": str(tmp_path / "service"), "service_uid": os.getuid(), "operator_uid": os.getuid()}
    )
    root = tmp_path / "shared"
    root.mkdir()
    entry = {
        "type": "directory",
        "path": str(root),
        "identity": mounts.identity(root),
        "registration": "source",
        "status": "removing",
    }
    data = {"mounts": {"shared": entry}}
    monkeypatch.setattr(
        mounts, "scan", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError())
    )
    with pytest.raises(PermissionError):
        control.mount(data, "clean-owned", {"name": "shared", "inventory": "unproven"})
    with pytest.raises(AgentboxError, match="incomplete"):
        control.mount(data, "forget", {"name": "shared"})
    assert data["mounts"]["shared"]["status"] == "removing"


@pytest.mark.parametrize("boundary", ["owned-pass", "forget"])
def test_directory_remove_retry_preserves_journal_and_files(tmp_path, monkeypatch, boundary):
    root = tmp_path / "shared"
    root.mkdir()
    (root / "data").write_text("retained")
    settings = {
        "operator_state": str(tmp_path / "journal"),
        "operator_uid": os.getuid(),
        "service_uid": 99997,
    }
    entry = {
        "type": "directory",
        "path": str(root),
        "identity": mounts.identity(root),
        "registration": "source",
        "status": "removing",
    }
    calls = []
    fail = [True]

    def rpc(request):
        calls.append(request["operation"])
        if request["operation"] == "forget" and boundary == "forget" and fail[0]:
            raise KeyboardInterrupt
        return dict(entry)

    def interrupt(*args):
        if boundary == "owned-pass" and fail[0]:
            raise KeyboardInterrupt

    monkeypatch.setattr(cli, "rpc", rpc)
    monkeypatch.setattr(cli, "_mount_attach_parents", lambda *args: calls.append("attach-parents"))
    monkeypatch.setattr(cli, "_mount_grant_root", lambda *args: None)
    monkeypatch.setattr(mounts, "clean_owned", interrupt)
    with pytest.raises(KeyboardInterrupt):
        cli.mount_remove(settings, "shared")
    with Store(settings["operator_state"]).locked() as journal:
        if boundary == "owned-pass":
            assert journal["mounts"]["shared"]["status"] == "removing"
            assert "forget" not in calls
        else:
            assert "shared" not in journal["mounts"]  # Journal commits before forget.
    assert calls.index("attach-parents") < calls.index("prepare-clean")
    assert (root / "data").read_text() == "retained"
    fail[0] = False
    cli.mount_remove(settings, "shared")
    assert calls[-1] == "forget" and (root / "data").read_text() == "retained"


def test_explicit_remove_can_forget_missing_volume(volume_control):
    control, present, mutations = volume_control
    present.clear()
    with control.store.locked() as data:
        assert control.mount(data, "prepare-remove", {"name": "profile"})["data"] == "deleted"
        assert "profile" not in data["mounts"] and not mutations


def test_retry_finishes_environment_after_agent_reference_is_gone(volume_control, monkeypatch):
    control, _, mutations = volume_control
    users = {
        "environment": {
            "operation": "remove",
            "containers": ["agent", "proxy"],
            "networks": ["inside"],
        }
    }
    monkeypatch.setattr(control, "mount_users", lambda *args, **kwargs: users)

    def fail_remove(data, name):
        raise OSError("network cleanup failed after agent removal")

    monkeypatch.setattr(control, "remove", fail_remove)
    with pytest.raises(OSError), control.store.locked() as data:
        control.mount(data, "prepare-remove", {"name": "profile", "yes": True})
    assert not mutations
    users = {}
    monkeypatch.setattr(
        control, "owned", lambda data, name, kind: ["proxy"] if kind == "container" else ["inside"]
    )
    cleaned = []
    monkeypatch.setattr(control, "remove", lambda data, name: cleaned.append(name))
    with control.store.locked() as data:
        assert (
            control.mount(data, "prepare-remove", {"name": "profile", "yes": True})["data"]
            == "deleted"
        )
    assert cleaned == ["environment"] and len(mutations) == 1


@pytest.mark.parametrize("status", ["active", "adding"])
def test_diagnosis_never_creates_a_missing_volume(monkeypatch, status):
    entry = {"type": "volume", "status": status}

    def rpc(request):
        if request["operation"] == "list":
            return {"profile": entry}
        assert request["operation"] == "check", "Diagnosis must not create or reactivate volumes"
        return entry | {"service_access_issues": ["Registered volume is missing"]}

    monkeypatch.setattr(cli, "rpc", rpc)
    result = cli.mount_check({}, "profile", fix=True)
    assert result["issues"] and not result["changed"] and result["status"] == status
