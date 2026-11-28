#!/bin/sh
# Param fw_cfg item opt/nexus.infinito.proxmox/first-boot: lines FQDN, ROOT_HASH, AUTHORIZED_KEY and HOST_KEY (base64 of the private ed25519 host key) that the launcher hands this guest.
# Param $RECORD: written before the launcher's key is admitted; image.<item> lines with what the guest booted with and deployed.<item> lines with what this hook made, as SSH host key fingerprints, SHA-256 of the machine id, SHA-256 fingerprints of the node certificate and the cluster CA, and SHA-256 of the root password hash.
set -eu

ITEM=/sys/firmware/qemu_fw_cfg/by_name/opt/nexus.infinito.proxmox/first-boot/raw
RECORD=/var/lib/infinito/first-boot.digests

fail() {
	printf '[FAIL] %s\n' "$*" >&2
	exit 1
}

value() {
	sed -n "s/^$1=//p" "$ITEM"
}

digest() {
	[ -z "$1" ] || printf '%s' "$1" | sha256sum | cut -d' ' -f1
}

certificate_fingerprint() {
	openssl x509 -noout -fingerprint -sha256 -in "$1" 2>/dev/null | sed -n 's/^.*Fingerprint=//p'
}

host_key_fingerprints() {
	for key in /etc/ssh/ssh_host_*_key.pub; do
		[ ! -r "$key" ] || ssh-keygen -lf "$key"
	done | awk '{ gsub(/[()]/, "", $NF); print $NF ":" $2 }' | sort | paste -sd, -
}

measure() {
	printf '%s.ssh_host_keys=%s\n' "$1" "$(host_key_fingerprints)"
	printf '%s.machine_id=%s\n' "$1" "$(digest "$(cat /etc/machine-id 2>/dev/null || :)")"
	printf '%s.node_certificate=%s\n' "$1" "$(certificate_fingerprint /etc/pve/local/pve-ssl.pem)"
	printf '%s.root_ca=%s\n' "$1" "$(certificate_fingerprint /etc/pve/pve-root-ca.pem)"
	printf '%s.root_hash=%s\n' "$1" "$(digest "$(getent shadow root | cut -d: -f2)")"
}

modprobe qemu_fw_cfg
[ -r "$ITEM" ] || fail "no first-boot values at $ITEM"

fqdn="$(value FQDN)"
root_hash="$(value ROOT_HASH)"
authorized_key="$(value AUTHORIZED_KEY)"
host_key="$(value HOST_KEY)"
[ -n "$fqdn" ] || fail "the first-boot value FQDN arrived empty"
[ -n "$root_hash" ] || fail "the first-boot value ROOT_HASH arrived empty"
[ -n "$authorized_key" ] || fail "the first-boot value AUTHORIZED_KEY arrived empty"
[ -n "$host_key" ] || fail "the first-boot value HOST_KEY arrived empty"

node="$(hostname -s)"
case "$fqdn" in
"$node".*) ;;
*) fail "FQDN $fqdn does not keep the node name $node, which pve-cluster fixed at install" ;;
esac
awk -v node="$node." -v fqdn="$fqdn" '{ for (i = 2; i <= NF; i++) if (index($i, node) == 1) $i = fqdn } 1' \
	/etc/hosts >/etc/hosts.first-boot
mv /etc/hosts.first-boot /etc/hosts

image_digests="$(measure image)"

rm -f /etc/ssh/ssh_host_*
umask 077
printf '%s' "$host_key" | base64 -d >/etc/ssh/ssh_host_ed25519_key
ssh-keygen -y -f /etc/ssh/ssh_host_ed25519_key >/etc/ssh/ssh_host_ed25519_key.pub
ssh-keygen -A
umask 022

rm -f /etc/machine-id /var/lib/dbus/machine-id
systemd-machine-id-setup
ln -sf /etc/machine-id /var/lib/dbus/machine-id

rm -f /etc/pve/priv/pve-root-ca.key /etc/pve/pve-root-ca.pem /etc/pve/priv/pve-root-ca.srl \
	/etc/pve/local/pve-ssl.key /etc/pve/local/pve-ssl.pem \
	/etc/pve/priv/authkey.key /etc/pve/authkey.pub
pvecm updatecerts --force

usermod -p "$root_hash" root
usermod -L root

printf 'AcceptEnv PROXMOX_*\nPasswordAuthentication no\nPermitRootLogin prohibit-password\nUsePAM yes\n' \
	>/etc/ssh/sshd_config.d/infinito.conf
systemctl restart ssh pvedaemon pveproxy

install -d -m 0700 "${RECORD%/*}"
{
	printf '%s\n' "$image_digests"
	measure deployed
} >"$RECORD"

install -d -m 0700 /root/.ssh
printf '%s\n' "$authorized_key" >>/root/.ssh/authorized_keys
