#!/usr/bin/env bash
# Administrator installation. Installs no Docker packages and changes no existing daemon.
set -euo pipefail
umask 077
case $# in
  0) operator_name=${SUDO_USER:-} ;;
  1)
    [[ $1 == --help || $1 == -h ]] && {
      echo 'Usage: sudo scripts/install.sh [--operator USER]'
      echo 'Defaults to the user invoking sudo. Direct root use requires --operator USER.'
      exit 0
    }
    echo 'Usage: sudo scripts/install.sh [--operator USER]' >&2; exit 2 ;;
  2)
    [[ $1 == --operator ]] || {
      echo 'Usage: sudo scripts/install.sh [--operator USER]' >&2; exit 2;
    }
    operator_name=$2 ;;
  *) echo 'Usage: sudo scripts/install.sh [--operator USER]' >&2; exit 2 ;;
esac
[[ $(id -u) == 0 ]] || { echo 'Run as root: sudo scripts/install.sh' >&2; exit 1; }
[[ -n "$operator_name" ]] || {
  echo 'Cannot infer the developer; use sudo or specify --operator USER' >&2; exit 2;
}
[[ "$operator_name" =~ ^[a-z_][a-z0-9_-]*$ ]] || {
  echo 'Invalid operator username' >&2; exit 2;
}
operator_uid=$(id -u "$operator_name")
[[ "$operator_uid" != 0 && "$operator_name" != agentbox ]] || { echo 'Choose a regular developer' >&2; exit 1; }
repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
for program in docker dockerd-rootless-setuptool.sh rootlesskit newuidmap newgidmap \
  getfacl setfacl systemctl loginctl visudo python3; do
  command -v "$program" >/dev/null || { echo "Missing prerequisite: $program" >&2; exit 1; }
done
python3 -I -c 'import venv'
[[ $(stat -fc %T /sys/fs/cgroup) == cgroup2fs ]] || { echo 'cgroup v2 is required' >&2; exit 1; }
if ! getent passwd agentbox >/dev/null; then
  useradd --create-home --home-dir /var/lib/agentbox --shell /bin/bash agentbox
fi
service_uid=$(id -u agentbox)
service_home=$(getent passwd agentbox | cut -d: -f6)
[[ "$service_home" == /var/lib/agentbox && "$service_uid" != 0 && "$service_uid" != "$operator_uid" ]] || {
  echo 'Existing agentbox account has unexpected home or UID; refusing changes' >&2; exit 1;
}
[[ ! -L /var/lib/agentbox && $(stat -c %u /var/lib/agentbox) == "$service_uid" ]] || {
  echo 'Unexpected service-home owner' >&2; exit 1;
}
[[ $(id -G agentbox) == "$(id -g agentbox)" && $(id -g agentbox) != 0 && $(id -gn agentbox) == agentbox ]] || {
  echo 'agentbox must have only its own unprivileged primary group' >&2; exit 1;
}
chmod 0700 /var/lib/agentbox
if [[ -f /etc/agentbox/settings.json ]]; then
  python3 -I - "$operator_uid" "$service_uid" <<'PY'
import json, sys
settings = json.load(open('/etc/agentbox/settings.json'))
assert settings['operator_uid'] == int(sys.argv[1]), 'Existing installation has a different operator'
assert settings['service_uid'] == int(sys.argv[2]), 'Service UID changed'
PY
fi
install -d -m 0755 /opt/agentbox/lib /opt/agentbox/security /etc/agentbox /usr/local/libexec
if [[ -n $(find "$repo_dir/src" "$repo_dir/security" "$repo_dir/images" "$repo_dir/proxy" -type l -print -quit) ]]; then
  echo 'Refusing installation from a source tree containing symlinks' >&2; exit 1
fi
cp -r -- "$repo_dir/src/agentbox" /opt/agentbox/lib/
find /opt/agentbox/lib/agentbox -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
find /opt/agentbox/lib/agentbox -type d -name __pycache__ -empty -delete
cp -r -- "$repo_dir/images" "$repo_dir/proxy" /opt/agentbox/
python3 "$repo_dir/src/agentbox/seccomp.py" > /opt/agentbox/security/seccomp.json
if [[ ! -x /opt/agentbox/venv/bin/python3 ]]; then
  python3 -m venv /opt/agentbox/venv
fi
/opt/agentbox/venv/bin/python3 -I -m pip --isolated install --disable-pip-version-check --no-deps PyYAML==6.0.2
chown -R root:root /opt/agentbox
chmod -R go-w /opt/agentbox
chmod -R a+rX /opt/agentbox
cat > /usr/local/bin/agentbox <<'EOF'
#!/opt/agentbox/venv/bin/python3 -I
import sys
sys.path.insert(0, '/opt/agentbox/lib')
from agentbox.cli import main
main()
EOF
cat > /usr/local/libexec/agentbox-control <<'EOF'
#!/opt/agentbox/venv/bin/python3 -I
import sys
sys.path.insert(0, '/opt/agentbox/lib')
from agentbox.cli import control_main
control_main()
EOF
cat > /usr/local/libexec/agentbox-watch <<'EOF'
#!/opt/agentbox/venv/bin/python3 -I
import sys
sys.path.insert(0, '/opt/agentbox/lib')
from agentbox.watch import main
main()
EOF
chmod 0755 /usr/local/bin/agentbox /usr/local/libexec/agentbox-control /usr/local/libexec/agentbox-watch
install -d -m 0755 /usr/local/share/bash-completion/completions
install -m 0644 "$repo_dir/src/agentbox/completions/agentbox.bash" \
  /usr/local/share/bash-completion/completions/agentbox
install -d -m 0755 /etc/systemd/user
cat > /etc/systemd/user/agentbox-watch.service <<'EOF'
[Unit]
Description=Stop agentbox environments when host addresses change
After=docker.service
Requires=docker.service
PartOf=docker.service

[Service]
ExecStart=/usr/local/libexec/agentbox-watch
Restart=on-failure
RestartSec=1

[Install]
WantedBy=default.target
EOF
chmod 0644 /etc/systemd/user/agentbox-watch.service
install -d -o "$operator_uid" -g "$(id -g "$operator_name")" -m 0700 /var/lib/agentbox-operator
python3 -I - "$operator_uid" "$service_uid" <<'PY'
import json, sys
from pathlib import Path
settings_path = Path('/etc/agentbox/settings.json')
previous = json.loads(settings_path.read_text()) if settings_path.exists() else {}
Path('/etc/agentbox/settings.json').write_text(json.dumps({
    'operator_uid': int(sys.argv[1]), 'service_uid': int(sys.argv[2]),
    'home': '/var/lib/agentbox', 'operator_state': '/var/lib/agentbox-operator',
    'proxy_image': 'agentbox-proxy:local', 'seccomp': '/opt/agentbox/security/seccomp.json',
    'network_pool': previous.get('network_pool', '172.28.0.0/16'),
}, indent=2) + '\n')
PY
chmod 0644 /etc/agentbox/settings.json
temporary_rule=$(mktemp)
trap 'rm -f -- "$temporary_rule"' EXIT
printf '%s ALL=(agentbox) NOPASSWD: /usr/local/libexec/agentbox-control ""\n' "$operator_name" > "$temporary_rule"
visudo -cf "$temporary_rule"
install -m 0440 "$temporary_rule" /etc/sudoers.d/agentbox
loginctl enable-linger agentbox
install -d -m 0755 "/etc/systemd/system/user@$service_uid.service.d"
cat > "/etc/systemd/system/user@$service_uid.service.d/agentbox.conf" <<'EOF'
[Service]
Delegate=cpu cpuset io memory pids
EOF
chmod 0644 "/etc/systemd/system/user@$service_uid.service.d/agentbox.conf"
systemctl daemon-reload
systemctl start "user@$service_uid.service"
runuser -u agentbox -- env -i PATH=/usr/bin:/bin HOME=/var/lib/agentbox \
  XDG_RUNTIME_DIR="/run/user/$service_uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$service_uid/bus" \
  dockerd-rootless-setuptool.sh install --force
runuser -u agentbox -- env -i PATH=/usr/bin:/bin HOME=/var/lib/agentbox \
  XDG_RUNTIME_DIR="/run/user/$service_uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$service_uid/bus" \
  systemctl --user daemon-reload
runuser -u agentbox -- env -i PATH=/usr/bin:/bin HOME=/var/lib/agentbox \
  XDG_RUNTIME_DIR="/run/user/$service_uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$service_uid/bus" \
  systemctl --user enable --now agentbox-watch.service
runuser -u agentbox -- env -i PATH=/usr/bin:/bin HOME=/var/lib/agentbox \
  XDG_RUNTIME_DIR="/run/user/$service_uid" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$service_uid/bus" \
  systemctl --user restart agentbox-watch.service
echo 'Installed. Run as the developer: agentbox doctor; agentbox build-images'
