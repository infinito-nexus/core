# Node image for the swarm DR test cluster, layered on the distro's infinito
# image so python + ansible + the CLI (venv) are already baked -- the per-node
# .deb bootstrap is gone. Adds only the node extras: dnsmasq (lab DNS), openssh
# server (backup pull chain), cryptsetup + e2fsprogs (LUKS drill device).
# Distro-agnostic install (apt/dnf/pacman) since INFINITO_IMAGE is per-distro.
# systemd-resolved is masked so it never races dnsmasq for port 53. The pacman
# branch refreshes the keyring and does a full -Syu: the pinned parent image can
# be weeks old, so a partial -Sy would hit unknown packager keys and would link
# fresh binaries against the image's older libraries.
ARG INFINITO_IMAGE
FROM ${INFINITO_IMAGE}

RUN set -eux; \
    if command -v apt-get >/dev/null 2>&1; then \
        apt-get update -qq; \
        apt-get install -y -qq --no-install-recommends dnsmasq openssh-server cryptsetup e2fsprogs; \
        rm -rf /var/lib/apt/lists/*; \
    elif command -v dnf >/dev/null 2>&1; then \
        dnf install -y dnsmasq openssh-server cryptsetup e2fsprogs; \
        dnf clean all; \
    elif command -v pacman >/dev/null 2>&1; then \
        pacman -Sy --noconfirm --needed archlinux-keyring; \
        pacman -Syu --noconfirm --needed dnsmasq openssh cryptsetup e2fsprogs; \
        rm -rf /var/cache/pacman/pkg/*; \
    else \
        echo "no supported package manager (apt/dnf/pacman)" >&2; exit 1; \
    fi; \
    systemctl mask systemd-resolved; \
    systemctl enable ssh 2>/dev/null || systemctl enable sshd; \
    mkdir -p /etc/systemd/journald.conf.d; \
    printf '[Journal]\nSystemMaxUse=256M\nRuntimeMaxUse=64M\n' > /etc/systemd/journald.conf.d/99-ci.conf; \
    rm -f /var/lib/dbus/machine-id; \
    truncate -s 0 /etc/machine-id
