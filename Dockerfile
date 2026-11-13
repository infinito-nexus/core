# Base image (pkgmgr) selector. SPOT lives in default.env's
# INFINITO_PARENT_IMAGE and is forwarded as a build arg by compose.yml /
# scripts/image/build.sh.
# Example values:
#   INFINITO_PARENT_IMAGE=ghcr.io/kevinveenbirkenbach/pkgmgr-arch:stable
# INFINITO_LINT_RUNNER (host|docker, SPOT default.env) selects the stage `full`
# builds on: lint-docker with the lint toolchain, lint-host without it.
ARG INFINITO_PARENT_IMAGE
# nocheck: dockerfile-arg-default
ARG INFINITO_LINT_RUNNER=host
FROM ${INFINITO_PARENT_IMAGE} AS base

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
  source <(grep -hE '^INFINITO_(FILESYSTEM_INSTALL_SCRIPT|APT_UBUNTU_MIRRORS|APT_UBUNTU_PORTS_MIRRORS)=' "${INFINITO_SRC_DIR}/default.env"); \
  INFINITO_APT_UBUNTU_MIRRORS="${INFINITO_APT_UBUNTU_MIRRORS:?}" \
  INFINITO_APT_UBUNTU_PORTS_MIRRORS="${INFINITO_APT_UBUNTU_PORTS_MIRRORS:?}" \
  /bin/bash "${INFINITO_SRC_DIR}/scripts/install/apt-mirrors.sh"; \
  /bin/bash "${INFINITO_SRC_DIR}/scripts/install/dnf-mirrors.sh"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_FILESYSTEM_INSTALL_SCRIPT:?}"

COPY roles/dev-python/files/shell ${INFINITO_SRC_DIR}/roles/dev-python/files/shell
COPY pyproject.toml ${INFINITO_SRC_DIR}/pyproject.toml
COPY roles/update/files/shell/centos_mirror.sh ${INFINITO_SRC_DIR}/roles/update/files/shell/centos_mirror.sh
COPY requirements ${INFINITO_SRC_DIR}/requirements
COPY utils/__init__.py ${INFINITO_SRC_DIR}/utils/__init__.py
COPY utils/install/__init__.py ${INFINITO_SRC_DIR}/utils/install/__init__.py
COPY utils/install/collections.py ${INFINITO_SRC_DIR}/utils/install/collections.py

# hadolint ignore=DL3008,DL3033,DL3041,SC1090,SC3040
RUN set -euo pipefail; \
  /bin/bash "${INFINITO_SRC_DIR}/roles/update/files/shell/centos_mirror.sh"; \
  source <(grep -hE '^INFINITO_PYTHON_INSTALL_SCRIPT=' "${INFINITO_SRC_DIR}/default.env"); \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_PYTHON_INSTALL_SCRIPT:?}" ensure; \
  VENV="${INFINITO_VENV_DIR}" bash "${INFINITO_SRC_DIR}/scripts/install/venv.sh"; \
  ${PIP} install --upgrade pip setuptools wheel; \
  ${PIP} install ansible PyYAML; \
  ANSIBLE_COLLECTIONS_DIR="${HOME}/.ansible/collections" \
    bash "${INFINITO_SRC_DIR}/scripts/install/ansible.sh"

FROM base AS lint-host

FROM base AS lint-docker

SHELL ["/bin/bash", "-o", "pipefail", "-lc"]

COPY packaging ${INFINITO_SRC_DIR}/packaging
COPY roles/sys-svc-container/files/shell ${INFINITO_SRC_DIR}/roles/sys-svc-container/files/shell
COPY roles/sys-lint/meta/services.yml ${INFINITO_SRC_DIR}/roles/sys-lint/meta/services.yml
COPY utils/cache/__init__.py ${INFINITO_SRC_DIR}/utils/cache/__init__.py
COPY utils/cache/files.py ${INFINITO_SRC_DIR}/utils/cache/files.py
COPY utils/cache/gitignore.py ${INFINITO_SRC_DIR}/utils/cache/gitignore.py
COPY utils/roles/__init__.py ${INFINITO_SRC_DIR}/utils/roles/__init__.py
COPY utils/roles/custom.py ${INFINITO_SRC_DIR}/utils/roles/custom.py
COPY utils/roles/mapping.py ${INFINITO_SRC_DIR}/utils/roles/mapping.py
COPY utils/install ${INFINITO_SRC_DIR}/utils/install

# hadolint ignore=DL3008,DL3033,DL3041,SC1090
RUN set -euo pipefail; \
  source <(grep -hE '^INFINITO_(PYTHON|DOCKER_CLI|PACKAGE|INTERPRETERS)_INSTALL_SCRIPT=' "${INFINITO_SRC_DIR}/default.env"); \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_PYTHON_INSTALL_SCRIPT:?}"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_DOCKER_CLI_INSTALL_SCRIPT:?}"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_PACKAGE_INSTALL_SCRIPT:?}"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_INTERPRETERS_INSTALL_SCRIPT:?}"

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN PYTHONPATH="${INFINITO_SRC_DIR}" python3 -m utils.install.lint action ansible python php ruby shellcheck dockerfile markdown mermaid makefile

# hadolint ignore=DL3006
FROM lint-${INFINITO_LINT_RUNNER} AS full

ARG NIX_CONFIG
ARG INFINITO_SRC_DIR
ARG INFINITO_VENV_DIR

SHELL ["/bin/bash", "-o", "pipefail", "-lc"]

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

RUN set -euo pipefail; \
  systemctl mask getty.target console-getty.service getty-static.service getty@.service

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
