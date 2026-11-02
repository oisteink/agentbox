#!/usr/bin/env bash
# Run as developer INSIDE the disposable VM. --uninstall destroys it last.
set -euo pipefail
umask 077
[[ $(hostname) == agentbox-lab && $(id -un) == developer ]] || {
  echo 'Run as developer only inside disposable agentbox-lab' >&2; exit 1;
}
[[ $# == 0 || ( $# == 1 && $1 == --uninstall ) ]] || {
  echo 'Usage: scripts/lab/check.sh [--uninstall]' >&2; exit 2;
}
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
cd -- "$repo_dir"
results_dir="$repo_dir/.lab/results"
mkdir -p -- "$results_dir"
python3 -m venv "$repo_dir/.lab/venv"
lab_python="$repo_dir/.lab/venv/bin/python"
# This small project has one lock resolution. Install its registry packages,
# including transitive dependencies, without pip resolving different versions.
python3 - <<'PY' > "$results_dir/requirements.txt"
import tomllib
from pathlib import Path

for package in tomllib.loads(Path('uv.lock').read_text())['package']:
    if 'registry' in package['source']:
        artifacts = package.get('wheels', []) + [package['sdist']]
        hashes = ' '.join('--hash=' + artifact['hash'] for artifact in artifacts)
        print(f"{package['name']}=={package['version']} {hashes}")
PY
"$lab_python" -I -m pip --isolated install --disable-pip-version-check \
  --no-deps --require-hashes -r "$results_dir/requirements.txt"
sudo bash scripts/install.sh --operator developer
abx proxy build
recipe_dir=${XDG_CONFIG_HOME:-$HOME/.config}/agentbox/images/codex
if [[ ! -e "$recipe_dir" ]]; then
  abx image new codex --template codex
fi
cp -- src/agentbox/templates/codex/Dockerfile src/agentbox/templates/codex/codex "$recipe_dir/"
abx image build codex
bash scripts/lab/build-images.sh
"$lab_python" - <<'PY' > "$results_dir/platform.json"
import hashlib
import json
import platform
import subprocess
from pathlib import Path

import pytest

installed = {}
for source, destination in (
    (Path('src/agentbox'), Path('/opt/agentbox/lib/agentbox')),
    (Path('proxy'), Path('/opt/agentbox/proxy')),
):
    expected = {p.relative_to(source) for p in source.rglob('*') if p.is_file()
                and '__pycache__' not in p.parts}
    actual = {p.relative_to(destination) for p in destination.rglob('*') if p.is_file()
              and '__pycache__' not in p.parts}
    assert actual == expected, f'Installed file set differs: {destination}'
    for relative in sorted(expected):
        data = (source / relative).read_bytes()
        assert data == (destination / relative).read_bytes(), f'Stale install: {relative}'
        installed[str(source / relative)] = hashlib.sha256(data).hexdigest()
uid = subprocess.check_output(['id', '-u', 'agentbox'], text=True).strip()
suite = {}
for directory in ('tests', 'scripts'):
    for path in Path(directory).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts:
            suite[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
for name in ('pyproject.toml', 'uv.lock'):
    suite[name] = hashlib.sha256(Path(name).read_bytes()).hexdigest()
images = subprocess.check_output([
    'sudo', '-u', 'agentbox', 'env', 'HOME=/var/lib/agentbox',
    f'XDG_RUNTIME_DIR=/run/user/{uid}', 'docker', '--host', f'unix:///run/user/{uid}/docker.sock',
    'image', 'inspect', '--format', '{{.RepoTags}} {{.Id}}',
    'agentbox-image-codex:local', 'agentbox-image-smoke:local', 'agentbox-proxy:local',
], text=True)
print(json.dumps({
    'platform': platform.platform(), 'os': platform.freedesktop_os_release(),
    'python': platform.python_version(), 'pytest': pytest.__version__,
    'installed_sha256': hashlib.sha256(json.dumps(installed, sort_keys=True).encode()).hexdigest(),
    'suite_sha256': hashlib.sha256(json.dumps(suite, sort_keys=True).encode()).hexdigest(),
    'installed_files': installed, 'images': images.splitlines(),
    'doctor': json.loads(subprocess.check_output(['abx', 'doctor'], text=True)),
}, indent=2, sort_keys=True))
PY

verify_report() {
  "$lab_python" - "$1" <<'PY'
import sys
import xml.etree.ElementTree as ET

suites = list(ET.parse(sys.argv[1]).getroot().iter('testsuite'))
assert sum(int(s.get('tests', 0)) for s in suites) > 0, 'No acceptance tests ran'
assert all(int(s.get('skipped', 0)) == 0 for s in suites), 'Skipped acceptance tests'
assert all(int(s.get('errors', 0)) + int(s.get('failures', 0)) == 0 for s in suites)
PY
}

# Run both even if one fails, while preserving a failing overall exit status.
failed=0
AGENTBOX_LAB=1 "$lab_python" -m pytest -q tests/integration/test_lifecycle.py \
  --junitxml="$results_dir/lifecycle.xml" || failed=1
verify_report "$results_dir/lifecycle.xml" || failed=1
sudo "$lab_python" scripts/lab/credential_proxy.py > "$results_dir/proxy.json" || failed=1
if [[ ${1:-} == --uninstall ]]; then
  sudo systemctl start docker
  AGENTBOX_UNINSTALL_LAB=1 "$lab_python" -m pytest -q tests/integration/test_uninstall.py \
    --junitxml="$results_dir/uninstall.xml" || failed=1
  verify_report "$results_dir/uninstall.xml" || failed=1
fi
exit "$failed"
