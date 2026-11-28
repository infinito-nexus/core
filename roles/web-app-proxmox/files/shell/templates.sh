#!/bin/sh
# Param PROXMOX_STORAGE: storage the templates' disks and cloud-init drives live on.
# Param PROXMOX_BRIDGE: bridge of the templates' network card.
# Param PROXMOX_IMAGE_URL: download URL of the pinned cloud image.
# Param PROXMOX_IMAGE_SHA256: SHA-256 the cloud image must have.
# Param PROXMOX_TEMPLATE_KVM: VM id of the template with KVM.
# Param PROXMOX_TEMPLATE_EMULATED: VM id of the emulated template.
# Output: one "[CHANGED] ..." line per template it built or replaced.
set -eu

fail() {
	printf '[FAIL] %s\n' "$*" >&2
	exit 1
}

for name in PROXMOX_STORAGE PROXMOX_BRIDGE PROXMOX_IMAGE_URL PROXMOX_IMAGE_SHA256 \
	PROXMOX_TEMPLATE_KVM PROXMOX_TEMPLATE_EMULATED; do
	[ -n "$(printenv "$name")" ] || fail "$name arrived empty"
done
[ "$PROXMOX_TEMPLATE_KVM" != "$PROXMOX_TEMPLATE_EMULATED" ] || fail "both templates have the VM id $PROXMOX_TEMPLATE_KVM"

MARKER="image-sha256=$PROXMOX_IMAGE_SHA256"

current() {
	qm config "$1" 2>/dev/null || return 0
}

is_current() {
	config="$(current "$1")"
	printf '%s\n' "$config" | grep -qx 'template: 1' &&
		printf '%s\n' "$config" | grep -qxF "description: $MARKER"
}

work=""
image=""

fetch_image() {
	[ -z "$image" ] || return 0
	work="$(mktemp -d)"
	trap 'rm -rf "$work"' EXIT
	image="$work/image.qcow2"
	curl --retry 3 --retry-all-errors --retry-delay 2 --connect-timeout 20 --max-time 1800 -fsSL "$PROXMOX_IMAGE_URL" -o "$image"
	actual="$(sha256sum "$image" | cut -d' ' -f1)"
	[ "$actual" = "$PROXMOX_IMAGE_SHA256" ] || fail "the cloud image has SHA-256 $actual, the pin is $PROXMOX_IMAGE_SHA256, so no template imports it"
}

build() {
	id="$1"
	name="$2"
	kvm="$3"
	cpu="$4"
	if is_current "$id"; then
		return 0
	fi
	fetch_image
	if [ -n "$(current "$id")" ]; then
		qm destroy "$id" --purge 1
	fi
	qm create "$id" \
		--name "$name" \
		--description "$MARKER" \
		--ostype l26 \
		--kvm "$kvm" \
		--cpu "$cpu" \
		--cores 1 \
		--memory 1024 \
		--agent enabled=1 \
		--scsihw virtio-scsi-pci \
		--serial0 socket \
		--vga serial0 \
		--net0 "virtio,bridge=$PROXMOX_BRIDGE"
	qm set "$id" --scsi0 "$PROXMOX_STORAGE:0,import-from=$image"
	qm set "$id" --ide2 "$PROXMOX_STORAGE:cloudinit" --boot order=scsi0
	qm template "$id"
	printf '[CHANGED] template %s (%s, kvm %s, cpu %s) built from %s\n' "$id" "$name" "$kvm" "$cpu" "$MARKER"
}

build "$PROXMOX_TEMPLATE_KVM" workspace-kvm 1 x86-64-v2-AES
build "$PROXMOX_TEMPLATE_EMULATED" workspace-emulated 0 qemu64
