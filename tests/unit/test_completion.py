import json
import shlex
import subprocess
from types import SimpleNamespace

import pytest

from agentbox import completion


def test_names_use_read_only_request_without_password_prompt(monkeypatch):
    seen = {}

    def run(command, **kwargs):
        seen.update(command=command, **kwargs)
        return SimpleNamespace(returncode=0, stdout=json.dumps({"pubnix-codex": {}, "other": {}}))

    monkeypatch.setattr(completion.subprocess, "run", run)
    assert completion.names("environments") == ["other", "pubnix-codex"]
    assert "-n" in seen["command"]
    assert seen["timeout"] == 2
    assert json.loads(seen["input"]) == {"action": "status"}
    completion.names("projects")
    assert json.loads(seen["input"]) == {"action": "project", "operation": "list"}


@pytest.mark.parametrize("response", ["invalid json", '["wrong shape"]', '{"bad name": {}}'])
def test_invalid_completion_response_is_ignored(monkeypatch, response):
    monkeypatch.setattr(
        completion.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=response),
    )
    assert completion.names("environments") == []


def test_completion_timeout_is_ignored(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("sudo", 2)

    monkeypatch.setattr(completion.subprocess, "run", run)
    assert completion.names("environments") == []


@pytest.mark.parametrize(
    "words,expected",
    [
        (["agentbox", "sh"], ["shell"]),
        (["agentbox", "shell", "pub"], ["pubnix-codex"]),
        (["agentbox", "logs", "pubnix-codex", "--p"], ["--proxy"]),
        (["agentbox", "project", "re"], ["repair", "revoke"]),
        (["agentbox", "project", "repair", "pub"], ["pubnix"]),
        (["agentbox", "exec", "pubnix-codex", "--", ""], []),
        (["agentbox", "start", "with"], ["with space.yaml"]),
        (["agentbox", "start", "pub"], ["pubnix-codex"]),
        (["agentbox", "validate", "pub"], ["pubnix-codex"]),
        (["agentbox", "start", "--h"], ["--help"]),
        (["agentbox", "project", "add", "pubnix", "--path", "proj"], ["project dir"]),
    ],
)
def test_bash_completion(words, expected, tmp_path):
    (tmp_path / "with space.yaml").touch()
    (tmp_path / "project dir").mkdir()
    script = (
        completion.bash_script()
        + """
agentbox() {
  case "$*" in
    'completion --names environments') printf '%s\\n' other pubnix-codex ;;
    'completion --names projects') printf '%s\\n' pubnix ;;
    'completion --names configs') printf '%s\\n' pubnix-codex ;;
    *) return 1 ;;
  esac
}
compopt() { :; }
"""
    )
    script += f"COMP_WORDS=({shlex.join(words)})\nCOMP_CWORD={len(words) - 1}\n"
    script += '_agentbox\nprintf "%s\\n" "${COMPREPLY[@]}"\n'
    result = subprocess.run(
        ["bash", "--noprofile", "--norc"],
        input=script,
        text=True,
        capture_output=True,
        cwd=tmp_path,
        check=True,
    )
    assert result.stderr == ""
    assert result.stdout.splitlines() == (expected or [""])


def test_config_name_completion_does_not_call_control(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    folder = tmp_path / "agentbox/environments"
    folder.mkdir(parents=True)
    for filename in ("saved.yaml", "saved.yml", "other.yml", "not yaml.txt", "bad name.yaml"):
        (folder / filename).write_text("This is deliberately not parsed during completion")
    (folder / "directory.yaml").mkdir()
    monkeypatch.setattr(
        completion.subprocess, "run", lambda *args, **kwargs: pytest.fail("No sudo lookup")
    )
    assert completion.names("configs") == ["other", "saved"]
