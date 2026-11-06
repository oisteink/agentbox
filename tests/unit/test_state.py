import json

import pytest

from agentbox.errors import AgentboxError
from agentbox.state import Store


def test_state_persists_and_exception_does_not_commit(tmp_path):
    store = Store(tmp_path / "private")
    with store.locked() as data:
        installation = data["installation"]
        data["mounts"]["example"] = {"path": "/example"}
    with pytest.raises(RuntimeError), store.locked() as data:
        data["mounts"].clear()
        raise RuntimeError("abort")
    with store.locked() as data:
        assert "example" in data["mounts"]
        assert data["installation"] == installation
    assert json.loads((store.root / "state.json").read_text())["schema"] == 2


def test_state_rejects_public_directory(tmp_path):
    path = tmp_path / "public"
    path.mkdir(mode=0o755)
    with pytest.raises(AgentboxError, match="0700"):
        Store(path)
