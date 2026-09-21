# Base image (pkgmgr) selector. SPOT lives in default.env's
# INFINITO_PARENT_IMAGE and is forwarded as a build arg by compose.yml /
# scripts/image/build.sh.
# Example values:
#   INFINITO_PARENT_IMAGE=ghcr.io/kevinveenbirkenbach/pkgmgr-arch:stable
ARG INFINITO_PARENT_IMAGE
FROM ${INFINITO_PARENT_IMAGE} AS full

ARG NIX_CONFIG

ARG INFINITO_SRC_DIR
ENV INFINITO_SRC_DIR=${INFINITO_SRC_DIR}
ARG INFINITO_VENV_DIR
ENV INFINITO_VENV_DIR=${INFINITO_VENV_DIR}
ENV PYTHON="${INFINITO_VENV_DIR}/bin/python"
ENV PIP="${INFINITO_VENV_DIR}/bin/python -m pip"
ENV PATH="${INFINITO_VENV_DIR}/bin:${PATH}"

# hadolint DL4006: ensure pipefail is set for RUN instructions that use pipes
SHELL ["/bin/bash", "-o", "pipefail", "-lc"]

RUN set -euo pipefail; \
  cat /etc/os-release || true; \
  if [ -f /etc/nix/nix.conf ]; then \
    grep -q '^accept-flake-config *= *true' /etc/nix/nix.conf || \
    echo 'accept-flake-config = true' >> /etc/nix/nix.conf; \
  fi

COPY default.env ${INFINITO_SRC_DIR}/default.env
COPY scripts/install ${INFINITO_SRC_DIR}/scripts/install

# hadolint ignore=SC1090
RUN set -euo pipefail; \
  source <(grep -hE '^INFINITO_(FILESYSTEM_INSTALL_SCRIPT|APT_UBUNTU_MIRRORS)=' "${INFINITO_SRC_DIR}/default.env"); \
  INFINITO_APT_UBUNTU_MIRRORS="${INFINITO_APT_UBUNTU_MIRRORS:?}" /bin/bash "${INFINITO_SRC_DIR}/scripts/install/apt-mirrors.sh"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_FILESYSTEM_INSTALL_SCRIPT:?}"

COPY roles/dev-python/files/shell ${INFINITO_SRC_DIR}/roles/dev-python/files/shell
COPY requirements ${INFINITO_SRC_DIR}/requirements
COPY utils/__init__.py ${INFINITO_SRC_DIR}/utils/__init__.py
COPY utils/install/__init__.py ${INFINITO_SRC_DIR}/utils/install/__init__.py
COPY utils/install/collections.py ${INFINITO_SRC_DIR}/utils/install/collections.py

# hadolint ignore=DL3008,DL3033,DL3041,SC1090,SC3040
RUN set -euo pipefail; \
  source <(grep -hE '^INFINITO_PYTHON_INSTALL_SCRIPT=' "${INFINITO_SRC_DIR}/default.env"); \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_PYTHON_INSTALL_SCRIPT:?}" ensure; \
  VENV="${INFINITO_VENV_DIR}" bash "${INFINITO_SRC_DIR}/scripts/install/venv.sh"; \
  ${PIP} install --upgrade pip setuptools wheel; \
  ${PIP} install ansible PyYAML; \
  ANSIBLE_COLLECTIONS_DIR="${HOME}/.ansible/collections" \
    bash "${INFINITO_SRC_DIR}/scripts/install/ansible.sh"

COPY . ${INFINITO_SRC_DIR}

# hadolint ignore=DL3008,DL3033,DL3041,SC1090
RUN set -euo pipefail; \
  source <(grep -hE '^INFINITO_(PYTHON|DOCKER_CLI|PACKAGE|INTERPRETERS)_INSTALL_SCRIPT=' "${INFINITO_SRC_DIR}/default.env"); \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_PYTHON_INSTALL_SCRIPT:?}"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_DOCKER_CLI_INSTALL_SCRIPT:?}"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_PACKAGE_INSTALL_SCRIPT:?}"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_INTERPRETERS_INSTALL_SCRIPT:?}"

RUN set -euo pipefail; \
  systemctl mask systemd-firstboot.service first-boot-complete.target \
    systemd-binfmt.service proc-sys-fs-binfmt_misc.automount \
    proc-sys-fs-binfmt_misc.mount || true; \
  systemd-machine-id-setup || true

ENV container=docker
STOPSIGNAL SIGRTMIN+3

# hadolint ignore=SC3040
RUN set -euo pipefail; \
  export NIX_CONFIG="${NIX_CONFIG:-}"; \
  "${INFINITO_SRC_DIR}/scripts/docker/entry.sh" --compile -- true

WORKDIR /

COPY scripts/docker/healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/healthcheck.sh
HEALTHCHECK --interval=5s --timeout=20s --start-period=30s --retries=20 \
  CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/bin/bash", "-c", "exec \"${INFINITO_SRC_DIR}/scripts/docker/entry.sh\" \"$@\"", "--"]

CMD ["/sbin/init"]
