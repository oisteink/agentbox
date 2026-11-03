#!/usr/bin/env bash
# Build only the disposable lab's fixture images, never the host daemon.
set -euo pipefail
[[ $(hostname) == agentbox-lab ]] || { echo 'Run only in disposable lab' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
recipe_dir=${XDG_CONFIG_HOME:-$HOME/.config}/agentbox/images/smoke
if [[ ! -e "$recipe_dir" ]]; then
  abx image new smoke
fi
cp -- "$repo_dir/images/smoke/Dockerfile" "$recipe_dir/Dockerfile"
abx image build smoke
