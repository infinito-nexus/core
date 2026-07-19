# syntax=docker/dockerfile:1

# Base image (pkgmgr) selector. SPOT lives in default.env's
# INFINITO_PARENT_IMAGE and is forwarded as a build arg by compose.yml /
# scripts/image/build.sh.
# Example values:
#   INFINITO_PARENT_IMAGE=ghcr.io/kevinveenbirkenbach/pkgmgr-arch:stable
ARG INFINITO_PARENT_IMAGE
FROM ${INFINITO_PARENT_IMAGE} AS full

# hadolint DL4006: ensure pipefail is set for RUN instructions that use pipes
SHELL ["/bin/bash", "-o", "pipefail", "-lc"]

ARG NIX_CONFIG

ARG INFINITO_SRC_DIR
ENV INFINITO_SRC_DIR=${INFINITO_SRC_DIR}
ARG INFINITO_VENV_DIR
ENV INFINITO_VENV_DIR=${INFINITO_VENV_DIR}
ENV PYTHON="${INFINITO_VENV_DIR}/bin/python"
ENV PIP="${INFINITO_VENV_DIR}/bin/python -m pip"
ENV PATH="${INFINITO_VENV_DIR}/bin:${PATH}"

RUN set -euo pipefail; \
  cat /etc/os-release || true; \
  if [ -f /etc/nix/nix.conf ]; then \
    grep -q '^accept-flake-config *= *true' /etc/nix/nix.conf || \
    echo 'accept-flake-config = true' >> /etc/nix/nix.conf; \
  fi

COPY . ${INFINITO_SRC_DIR}

# hadolint ignore=DL3008,DL3033,DL3041,SC1090
RUN set -euo pipefail; \
  source <(grep -hE '^INFINITO_(PYTHON|DOCKER_CLI|PACKAGE)_INSTALL_SCRIPT=' "${INFINITO_SRC_DIR}/default.env"); \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_PYTHON_INSTALL_SCRIPT:?}"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_DOCKER_CLI_INSTALL_SCRIPT:?}"; \
  /bin/bash "${INFINITO_SRC_DIR}/${INFINITO_PACKAGE_INSTALL_SCRIPT:?}"

RUN set -euo pipefail; \
  systemctl mask systemd-firstboot.service first-boot-complete.target || true; \
  systemd-machine-id-setup || true

ENV container=docker
STOPSIGNAL SIGRTMIN+3

RUN set -euo pipefail; \
  export NIX_CONFIG="${NIX_CONFIG:-}"; \
  "${INFINITO_SRC_DIR}/scripts/docker/entry.sh" --compile -- true

WORKDIR /

COPY scripts/docker/healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/healthcheck.sh
HEALTHCHECK --interval=5s --timeout=20s --start-period=30s --retries=20 \
  CMD /usr/local/bin/healthcheck.sh

ENTRYPOINT ["/bin/bash", "-c", "exec \"${INFINITO_SRC_DIR}/scripts/docker/entry.sh\" \"$@\"", "--"]

CMD ["/sbin/init"]
