#!/usr/bin/env bash
# Administrator uninstall, independent of the installed CLI and its private venv.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 -I - "$repo_dir/src" "$@" <<'PY'
import sys
sys.path.insert(0, sys.argv.pop(1))
from agentbox.uninstall import main
main()
PY
