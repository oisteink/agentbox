#!/usr/bin/env bash
# Run ONLY inside the disposable Ubuntu lab: vm.sh ssh sudo bash -s < this-file.
set -euo pipefail
[[ $(id -u) == 0 ]] || { echo 'Root required in lab VM' >&2; exit 1; }
[[ $(hostname) == agentbox-lab ]] || { echo 'Refusing to modify a non-lab host' >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl acl uidmap dbus-user-session \
  slirp4netns python3 python3-yaml python3-pytest python3-venv iproute2 dnsutils

install -d -m 0755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
chmod 0644 /etc/apt/keyrings/docker.asc
cat > /etc/apt/sources.list.d/docker.sources <<'EOF'
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: noble
Components: stable
Architectures: amd64
Signed-By: /etc/apt/keyrings/docker.asc
EOF
apt-get update -qq
if [[ ! -e /usr/sbin/policy-rc.d ]]; then
  printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d
  chmod 0755 /usr/sbin/policy-rc.d
  trap 'rm -f /usr/sbin/policy-rc.d' EXIT
fi
apt-get install -y -qq docker-ce docker-ce-cli containerd.io \
  docker-ce-rootless-extras docker-buildx-plugin

if ! getent passwd agentbox >/dev/null; then
  useradd --create-home --home-dir /var/lib/agentbox --shell /bin/bash agentbox
fi
chmod 0700 /var/lib/agentbox
install -d -m 0755 /etc/systemd/system/user@.service.d
cat > /etc/systemd/system/user@.service.d/agentbox-lab.conf <<'EOF'
[Service]
Delegate=cpu cpuset io memory pids
EOF
systemctl daemon-reload
modprobe nf_tables
modprobe ip_tables
modprobe iptable_mangle
modprobe iptable_nat
modprobe iptable_filter
loginctl enable-linger agentbox
agent_uid=$(id -u agentbox)
systemctl start "user@$agent_uid.service"
runuser -u agentbox -- env HOME=/var/lib/agentbox \
  XDG_RUNTIME_DIR="/run/user/$agent_uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$agent_uid/bus" \
  dockerd-rootless-setuptool.sh install
runuser -u agentbox -- env HOME=/var/lib/agentbox \
  XDG_RUNTIME_DIR="/run/user/$agent_uid" \
  docker --host "unix:///run/user/$agent_uid/docker.sock" info
