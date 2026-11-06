#!/usr/bin/env bash
# Disposable KVM lab; no access to host mount directories is shared with the VM.
set -euo pipefail
umask 077

repo_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
lab_dir="$repo_dir/.lab"
image_name=ubuntu-24.04-minimal-cloudimg-amd64.img
image_url="https://cloud-images.ubuntu.com/minimal/releases/noble/release"
ssh_port=22482

mkdir -p -- "$lab_dir"

vm_running() {
  [[ -f "$lab_dir/qemu.pid" ]] || return 1
  local pid
  read -r pid < "$lab_dir/qemu.pid"
  [[ "$pid" =~ ^[0-9]+$ ]] || return 1
  [[ -r "/proc/$pid/cmdline" ]] || return 1
  tr '\0' '\n' < "/proc/$pid/cmdline" | grep -Fxq 'agentbox-mvp-lab'
}

case "${1:-}" in
  prepare)
    for tool in curl sha256sum qemu-img xorriso ssh-keygen; do
      command -v "$tool" >/dev/null || { echo "Missing: $tool" >&2; exit 1; }
    done
    if [[ ! -f "$lab_dir/$image_name" ]]; then
      curl --fail --location --retry 3 "$image_url/$image_name" -o "$lab_dir/$image_name.part"
      curl --fail --location "$image_url/SHA256SUMS" -o "$lab_dir/SHA256SUMS"
      checksum=$(awk -v name="$image_name" '$2 == name || $2 == "*" name { print $1 }' "$lab_dir/SHA256SUMS")
      [[ "$checksum" =~ ^[a-f0-9]{64}$ ]] || { echo 'Missing image checksum' >&2; exit 1; }
      printf '%s  %s\n' "$checksum" "$lab_dir/$image_name.part" | sha256sum --check -
      mv -- "$lab_dir/$image_name.part" "$lab_dir/$image_name"
    fi
    [[ -f "$lab_dir/id_ed25519" ]] || ssh-keygen -q -t ed25519 -N '' -f "$lab_dir/id_ed25519"
    if [[ ! -f "$lab_dir/disk.qcow2" ]]; then
      qemu-img create -f qcow2 -F qcow2 -b "$lab_dir/$image_name" "$lab_dir/disk.qcow2" 24G
    fi
    pubkey=$(cat "$lab_dir/id_ed25519.pub")
    cat > "$lab_dir/user-data" <<EOF
#cloud-config
hostname: agentbox-lab
ssh_pwauth: false
users:
  - name: developer
    shell: /bin/bash
    groups: [sudo]
    sudo: ["ALL=(ALL) NOPASSWD:ALL"]
    ssh_authorized_keys:
      - $pubkey
EOF
    printf 'instance-id: agentbox-mvp-lab\nlocal-hostname: agentbox-lab\n' > "$lab_dir/meta-data"
    xorriso -as mkisofs -quiet -volid cidata -joliet -rock -output "$lab_dir/seed.iso" \
      "$lab_dir/user-data" "$lab_dir/meta-data"
    ;;
  start)
    if vm_running; then echo 'Lab already running'; exit 0; fi
    [[ -r /dev/kvm && -w /dev/kvm ]] || { echo 'KVM is required' >&2; exit 1; }
    [[ -f "$lab_dir/seed.iso" ]] || { echo 'Run prepare first' >&2; exit 1; }
    qemu-system-x86_64 -name agentbox-mvp-lab -enable-kvm -cpu host -smp 4 -m 6144 \
      -drive "file=$lab_dir/disk.qcow2,format=qcow2,if=virtio" \
      -drive "file=$lab_dir/seed.iso,format=raw,if=virtio,readonly=on" \
      -netdev "user,id=net0,hostfwd=tcp:127.0.0.1:$ssh_port-:22" \
      -device virtio-net-pci,netdev=net0 -display none \
      -serial "file:$lab_dir/console.log" -monitor none -daemonize -pidfile "$lab_dir/qemu.pid"
    echo "Started lab. SSH: $0 ssh"
    ;;
  ssh)
    shift
    exec ssh -i "$lab_dir/id_ed25519" -p "$ssh_port" \
      -o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new \
      -o "UserKnownHostsFile=$lab_dir/known_hosts" developer@127.0.0.1 "$@"
    ;;
  stop)
    if vm_running; then
      "$0" ssh sudo systemctl poweroff >/dev/null 2>&1 || true
      for attempt in {1..15}; do
        vm_running || break
        sleep 1
      done
      if ! vm_running; then
        echo 'Stopped disposable lab cleanly; disk retained under .lab/'
        exit 0
      fi
      read -r pid < "$lab_dir/qemu.pid"
      kill -TERM "$pid"
      echo 'Stopped disposable lab; disk retained under .lab/'
    else echo 'Lab is not running'; fi
    ;;
  *) echo "Usage: $0 {prepare|start|ssh [command...]|stop}" >&2; exit 2 ;;
esac
