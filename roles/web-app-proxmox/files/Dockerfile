ARG PROXMOX_BASE_IMAGE
ARG PROXMOX_BASE_VERSION
FROM ${PROXMOX_BASE_IMAGE}:${PROXMOX_BASE_VERSION}

ARG PROXMOX_REPOSITORY
ARG PROXMOX_KEYRING
ARG PROXMOX_KEYRING_SHA512
ARG PROXMOX_SUITE
ARG PROXMOX_PACKAGES

ENV DEBIAN_FRONTEND=noninteractive

RUN test -n "${PROXMOX_KEYRING_SHA512}" \
 && for pin in ${PROXMOX_PACKAGES}; do printf '%s\n' "${pin}" | grep -Eq '^[a-z0-9][a-z0-9.+-]*=[0-9A-Za-z.+~:-]+$' || { echo "unpinned or malformed package: ${pin}" >&2; exit 1; }; done \
 && rm -rf /var/lib/apt/lists/* \
 && apt-get -o Acquire::Retries=3 update \
 && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates curl \
 && curl --retry 3 --connect-timeout 10 --max-time 120 -fsSL "${PROXMOX_KEYRING}" -o /usr/share/keyrings/proxmox-archive-keyring.gpg \
 && echo "${PROXMOX_KEYRING_SHA512}  /usr/share/keyrings/proxmox-archive-keyring.gpg" | sha512sum -c - \
 && printf 'Types: deb\nURIs: %s\nSuites: %s\nComponents: pve-no-subscription\nSigned-By: /usr/share/keyrings/proxmox-archive-keyring.gpg\n' \
    "${PROXMOX_REPOSITORY}" "${PROXMOX_SUITE}" > /etc/apt/sources.list.d/pve-no-subscription.sources \
 && rm -rf /var/lib/apt/lists/* \
 && apt-get -o Acquire::Retries=3 update \
 && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ${PROXMOX_PACKAGES} systemd-sysv \
 && rm -rf /var/lib/apt/lists/*

STOPSIGNAL SIGRTMIN+3

CMD ["/sbin/init"]
