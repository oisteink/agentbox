#!/usr/bin/env bash
# Build only the disposable lab's fixture images, never the host daemon.
set -euo pipefail
[[ $(hostname) == agentbox-lab ]] || { echo 'Run only in disposable lab' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
service_uid=$(id -u agentbox)
for entry in 'agentbox-dev:lab images/smoke' 'agentbox-proxy:lab proxy'; do
  read -r image directory <<< "$entry"
  tar -C "$repo_dir/$directory" -cf - . |
    sudo -u agentbox env -i PATH=/usr/bin:/bin HOME=/var/lib/agentbox \
      XDG_RUNTIME_DIR="/run/user/$service_uid" \
      docker --host "unix:///run/user/$service_uid/docker.sock" build --tag "$image" -
done
