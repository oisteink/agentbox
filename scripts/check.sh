#!/usr/bin/env bash
# Local checks only. Installed behavior is verified by scripts/lab/check.sh.
set -euo pipefail
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd -- "$repo_dir"
uv sync --extra dev --locked
uv run --locked pytest -q
uv run --locked ruff check src tests scripts
uv run --locked ruff format --check src tests scripts
for script in scripts/*.sh scripts/lab/*.sh src/agentbox/templates/codex/codex src/agentbox/completions/abx.bash; do
  bash -n "$script" || exit
done
(
  cd proxy
  GOTOOLCHAIN=go1.27.3 go test -race ./...
  GOTOOLCHAIN=go1.27.3 go vet ./...
  GOTOOLCHAIN=go1.27.3 go run golang.org/x/vuln/cmd/govulncheck@v1.9.0 ./...
)
test -z "$(gofmt -l proxy/*.go)"
