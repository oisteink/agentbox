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
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(
                {"type": "result", "ok": True, "data": {"example-codex": {}, "other": {}}}
            ),
        )

    monkeypatch.setattr(completion.subprocess, "run", run)
    assert completion.names("environments") == ["example-codex", "other"]
    assert "-n" in seen["command"]
    assert seen["timeout"] == 2
    assert json.loads(seen["input"]) == {"action": "status"}
    completion.names("mounts")
    assert json.loads(seen["input"]) == {"action": "mount", "operation": "list"}


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
        (["abx", "sh"], ["shell"]),
        (["abx", "--js"], ["--json"]),
        (["abx", "--json", "sh"], ["shell"]),
        (["abx", "--json", "--yes", "image", "b"], ["build"]),
        (["abx", "image", "b"], ["build"]),
        (["abx", "image", "build", "j"], ["js"]),
        (["abx", "image", "e"], ["edit"]),
        (["abx", "image", "edit", "j"], ["js"]),
        (["abx", "image", "new", "js", "--template", "c"], ["codex", "claude-code"]),
        (["abx", "image", "new", "js", "--template", "o"], ["opencode"]),
        (["abx", "proxy", "b"], ["build"]),
        (["abx", "shell", "exa"], ["example-codex"]),
        (["abx", "logs", "example-codex", "--p"], ["--proxy"]),
        (["abx", "mount", "re"], ["revoke", "remove"]),
        (["abx", "mount", "check", "--fix", "exa"], ["example"]),
        (["abx", "exec", "example-codex", "--", ""], []),
        (["abx", "start", "with"], ["with space.yaml"]),
        (["abx", "start", "exa"], ["example-codex"]),
        (["abx", "run", "exa"], ["example-codex"]),
        (["abx", "validate", "exa"], ["example-codex"]),
        (["abx", "start", "--h"], ["--help"]),
        (["abx", "mount", "add", "example", "mou"], ["mount dir"]),
    ],
)
def test_bash_completion(words, expected, tmp_path):
    (tmp_path / "with space.yaml").touch()
    (tmp_path / "mount dir").mkdir()
    script = (
        completion.bash_script()
        + """
abx() {
  case "$*" in
    'completion --names environments') printf '%s\\n' other example-codex ;;
    'completion --names mounts') printf '%s\\n' example ;;
    'completion --names configs') printf '%s\\n' example-codex ;;
    'completion --names images') printf '%s\\n' js ;;
    *) return 1 ;;
  esac
}
compopt() { :; }
"""
    )
    script += '[[ $(complete -p abx) == "complete -F _abx abx" ]] || exit 1\n'
    script += f"COMP_WORDS=({shlex.join(words)})\nCOMP_CWORD={len(words) - 1}\n"
    script += '_abx\nprintf "%s\\n" "${COMPREPLY[@]}"\n'
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
