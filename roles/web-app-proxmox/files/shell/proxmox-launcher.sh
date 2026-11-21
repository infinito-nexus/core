#!/bin/sh
# Param $1: run (default) boots the guest, build keeps a base disk of the pinned ISO, tag prints the image tag, verify-iso <file> checks a file against the ISO pin.
# Param PROXMOX_LAUNCHER_SHARE: directory of the image's ISO pin (iso.sha256), answer.toml and first-boot.sh.
# Param PROXMOX_GUEST_DIR: volume of the guest overlay, its first-boot values and the guest channel's SSH files.
# Param PROXMOX_GUEST_BASE_DIR: volume of the base disks the image build keeps.
# Param PROXMOX_GUEST_NODE: node name the installed guest carries.
# Param PROXMOX_GUEST_FQDN: fully qualified name the first boot gives the guest.
# Param PROXMOX_GUEST_CPUS: vCPUs of the guest.
# Param PROXMOX_GUEST_MEMORY: memory of the guest, as QEMU reads -m.
# Param PROXMOX_GUEST_DISK: size of the guest disk, as qemu-img reads it.
# Param PROXMOX_GUEST_SSH_PORT: port on the container loopback that reaches the guest's SSH.
# Param PROXMOX_GUEST_API_PORT: container port that reaches the guest's pveproxy.
# Param PROXMOX_ISO_URL: download URL of the pinned installer ISO.
set -eu

FW_CFG_ITEM="opt/nexus.infinito.proxmox/first-boot"
MIN_INSTALLED_BYTES=1073741824

fail() {
	printf '[FAIL] %s\n' "$*" >&2
	exit 1
}

need() {
	for name in "$@"; do
		[ -n "$(printenv "$name")" ] || fail "$name arrived empty"
	done
}

image_tag() {
	need PROXMOX_LAUNCHER_SHARE
	cat "$PROXMOX_LAUNCHER_SHARE/iso.sha256" \
		"$PROXMOX_LAUNCHER_SHARE/answer.toml" \
		"$PROXMOX_LAUNCHER_SHARE/first-boot.sh" | sha256sum | cut -c1-16
}

verify_iso() {
	need PROXMOX_LAUNCHER_SHARE
	expected="$(tr -d '[:space:]' <"$PROXMOX_LAUNCHER_SHARE/iso.sha256")"
	[ -n "$expected" ] || fail "the image carries no ISO pin"
	actual="$(sha256sum "$1" | cut -d' ' -f1)"
	[ "$actual" = "$expected" ] || fail "$1 has SHA-256 $actual, the pin is $expected, so the build refuses it"
}

discarded_password_hash() {
	head -c 48 /dev/urandom | base64 | tr -d '\n' | openssl passwd -6 -stdin
}

base_disk() {
	printf '%s/base-%s.qcow2\n' "$PROXMOX_GUEST_BASE_DIR" "$(image_tag)"
}

build_base() {
	need PROXMOX_GUEST_BASE_DIR PROXMOX_ISO_URL PROXMOX_GUEST_CPUS PROXMOX_GUEST_MEMORY PROXMOX_GUEST_DISK
	base="$(base_disk)"
	[ ! -f "$base" ] || return 0
	work="$PROXMOX_GUEST_BASE_DIR/build"
	rm -rf "$work"
	mkdir -p "$work"
	curl --retry 3 --retry-all-errors --retry-delay 2 --connect-timeout 20 --max-time 3600 -fsSL "$PROXMOX_ISO_URL" -o "$work/installer.iso"
	verify_iso "$work/installer.iso"
	sed "s|@ROOT_PASSWORD_HASHED@|$(discarded_password_hash)|" \
		"$PROXMOX_LAUNCHER_SHARE/answer.toml" >"$work/answer.toml"
	proxmox-auto-install-assistant validate-answer "$work/answer.toml"
	proxmox-auto-install-assistant prepare-iso "$work/installer.iso" \
		--fetch-from iso \
		--answer-file "$work/answer.toml" \
		--on-first-boot "$PROXMOX_LAUNCHER_SHARE/first-boot.sh" \
		--output "$work/auto.iso"
	rm -f "$work/installer.iso" "$work/answer.toml"
	qemu-img create -q -f qcow2 "$work/base.qcow2" "$PROXMOX_GUEST_DISK"
	timeout 3h qemu-system-x86_64 \
		-nodefaults -no-user-config -no-reboot \
		-machine q35,accel=kvm -cpu host \
		-smp "$PROXMOX_GUEST_CPUS" -m "$PROXMOX_GUEST_MEMORY" \
		-display none -serial stdio \
		-drive "file=$work/base.qcow2,if=virtio,format=qcow2" \
		-drive "file=$work/auto.iso,media=cdrom,readonly=on" \
		-boot once=d \
		-netdev user,id=net0 -device virtio-net-pci,netdev=net0 </dev/null
	installed="$(qemu-img info --output=json "$work/base.qcow2" | sed -n 's/.*"actual-size": *\([0-9][0-9]*\).*/\1/p')"
	[ "${installed:-0}" -gt "$MIN_INSTALLED_BYTES" ] || fail "the installer powered off before it wrote Proxmox VE to the disk"
	mv "$work/base.qcow2" "$base"
	rm -rf "$work"
}

ssh_files() {
	ssh_dir="$PROXMOX_GUEST_DIR/ssh"
	install -d -m 0700 "$ssh_dir"
	[ -f "$ssh_dir/id_ed25519" ] || ssh-keygen -q -t ed25519 -N '' -C launcher -f "$ssh_dir/id_ed25519"
	[ -f "$ssh_dir/host_ed25519" ] || ssh-keygen -q -t ed25519 -N '' -C "$PROXMOX_GUEST_FQDN" -f "$ssh_dir/host_ed25519"
	printf 'pve-guest %s\n' "$(cut -d' ' -f1,2 "$ssh_dir/host_ed25519.pub")" >"$ssh_dir/known_hosts"
	cat >"$ssh_dir/config" <<EOF
Host guest
	HostName 127.0.0.1
	Port $PROXMOX_GUEST_SSH_PORT
	User root
	HostKeyAlias pve-guest
	IdentityFile $ssh_dir/id_ed25519
	IdentitiesOnly yes
	UserKnownHostsFile $ssh_dir/known_hosts
	StrictHostKeyChecking yes
	BatchMode yes
	ConnectTimeout 10
	SendEnv PROXMOX_*
	LogLevel ERROR
EOF
}

first_boot_values() {
	ssh_dir="$PROXMOX_GUEST_DIR/ssh"
	umask 077
	{
		printf 'FQDN=%s\n' "$PROXMOX_GUEST_FQDN"
		printf 'ROOT_HASH=%s\n' "$(discarded_password_hash)"
		printf 'AUTHORIZED_KEY=%s\n' "$(cat "$ssh_dir/id_ed25519.pub")"
		printf 'HOST_KEY=%s\n' "$(base64 -w0 "$ssh_dir/host_ed25519")"
	} >"$PROXMOX_GUEST_DIR/first-boot.env"
}

stop_guest() {
	if ! pve-guest poweroff >/dev/null 2>&1; then
		kill -TERM "$qemu" 2>/dev/null || return 0
	fi
}

run_guest() {
	need PROXMOX_GUEST_DIR PROXMOX_GUEST_BASE_DIR PROXMOX_GUEST_NODE PROXMOX_GUEST_FQDN \
		PROXMOX_GUEST_CPUS PROXMOX_GUEST_MEMORY PROXMOX_GUEST_SSH_PORT PROXMOX_GUEST_API_PORT
	case "$PROXMOX_GUEST_FQDN" in
	"$PROXMOX_GUEST_NODE".*) ;;
	*) fail "PROXMOX_GUEST_FQDN $PROXMOX_GUEST_FQDN does not keep the node name $PROXMOX_GUEST_NODE" ;;
	esac
	overlay="$PROXMOX_GUEST_DIR/overlay.qcow2"
	ssh_files
	if [ ! -f "$overlay" ]; then
		build_base
		first_boot_values
		qemu-img create -q -f qcow2 -F qcow2 -b "$(base_disk)" "$overlay"
	fi
	qemu-system-x86_64 \
		-name "$PROXMOX_GUEST_NODE" \
		-nodefaults -no-user-config \
		-machine q35,accel=kvm -cpu host \
		-smp "$PROXMOX_GUEST_CPUS" -m "$PROXMOX_GUEST_MEMORY" \
		-display none -serial stdio \
		-drive "file=$overlay,if=virtio,format=qcow2" \
		-netdev "user,id=net0,hostfwd=tcp:0.0.0.0:$PROXMOX_GUEST_API_PORT-:8006,hostfwd=tcp:127.0.0.1:$PROXMOX_GUEST_SSH_PORT-:22" \
		-device virtio-net-pci,netdev=net0 \
		-device virtio-rng-pci \
		-fw_cfg "name=$FW_CFG_ITEM,file=$PROXMOX_GUEST_DIR/first-boot.env" </dev/null &
	qemu=$!
	trap stop_guest TERM INT
	status=0
	while kill -0 "$qemu" 2>/dev/null; do
		if wait "$qemu"; then
			status=0
		else
			status=$?
		fi
	done
	exit "$status"
}

case "${1:-run}" in
run) run_guest ;;
build) build_base ;;
tag) image_tag ;;
verify-iso)
	[ "$#" -eq 2 ] || fail "verify-iso takes one file"
	verify_iso "$2"
	;;
*) fail "unknown command $1" ;;
esac
