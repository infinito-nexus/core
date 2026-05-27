# syntax=docker/dockerfile:1

# Base image (pkgmgr) selector. SPOT lives in default.env's
# INFINITO_PARENT_IMAGE and is forwarded as a build arg by compose.yml /
# scripts/image/build.sh.
# Example values:
#   INFINITO_PARENT_IMAGE=ghcr.io/kevinveenbirkenbach/pkgmgr-arch:stable
ARG INFINITO_PARENT_IMAGE
FROM ${INFINITO_PARENT_IMAGE} AS full

# Hadolint DL4006: ensure pipefail is set for RUN instructions that use pipes
SHELL ["/bin/bash", "-o", "pipefail", "-lc"]

# Forwardable build-time Nix settings (e.g., GitHub access tokens to avoid rate limits)
ARG NIX_CONFIG

# SPOT for the bind-mounted source tree inside the container. The compose
# stack forwards default.env's INFINITO_SRC_DIR as a build arg.
ARG INFINITO_SRC_DIR
ENV INFINITO_SRC_DIR=${INFINITO_SRC_DIR}
ENV PYTHON="/opt/venvs/infinito/bin/python"
ENV PIP="/opt/venvs/infinito/bin/python -m pip"
ENV PATH="/opt/venvs/infinito/bin:${PATH}"

# Make Nix non-interactive for flake config (CI-friendly)
RUN set -euo pipefail; \
  cat /etc/os-release || true; \
  if [ -f /etc/nix/nix.conf ]; then \
    grep -q '^accept-flake-config *= *true' /etc/nix/nix.conf || \
    echo 'accept-flake-config = true' >> /etc/nix/nix.conf; \
  fi

# ------------------------------------------------------------
# Infinito.Nexus source in
# ------------------------------------------------------------
COPY . ${INFINITO_SRC_DIR}

# ------------------------------------------------------------
# Install Python 3.11+, Docker CLI, and distro package dependencies
# ------------------------------------------------------------
# hadolint ignore=DL3008,DL3033,DL3041
RUN set -euo pipefail; \
  /bin/bash ${INFINITO_SRC_DIR}/roles/dev-python/files/install.sh; \
  /bin/bash ${INFINITO_SRC_DIR}/roles/sys-svc-container/files/install-cli.sh; \
  /bin/bash ${INFINITO_SRC_DIR}/scripts/install/package.sh

# ------------------------------------------------------------
# Disable interactive first-boot units (CI / container safe)
# ------------------------------------------------------------
RUN set -euo pipefail; \
  systemctl mask systemd-firstboot.service first-boot-complete.target || true; \
  systemd-machine-id-setup || true

# systemd-in-container conventions
ENV container=docker
STOPSIGNAL SIGRTMIN+3

# ------------------------------------------------------------
# Install infinito via pkgmgr (shallow) and override it with local source
# ------------------------------------------------------------
RUN set -euo pipefail; \
  export NIX_CONFIG="${NIX_CONFIG:-}"; \
  echo "[docker-infinito] Install Infinito.Nexus via pkgmgr"; \
  pkgmgr install infinito --clone-mode shallow; \
  echo "[docker-infinito] Installed Infinito.Nexus Version:"; \
  pkgmgr version infinito; \
  "${INFINITO_SRC_DIR}/scripts/docker/entry.sh" --compile -- true

# Set workdir to / to avoid ambiguous commands
WORKDIR /

COPY scripts/docker/healthcheck.sh /usr/local/bin/healthcheck.sh
RUN chmod +x /usr/local/bin/healthcheck.sh
# Allow 20s because `infinito --help` can exceed 5s on fresh CI runners.
HEALTHCHECK --interval=5s --timeout=20s --start-period=30s --retries=20 \
  CMD /usr/local/bin/healthcheck.sh

# JSON-form ENTRYPOINT does not expand ENV vars; wrap via bash -c so the
# INFINITO_SRC_DIR SPOT still controls the path. `exec` preserves systemd
# signal forwarding; `--` is the placeholder for $0.
ENTRYPOINT ["/bin/bash", "-c", "exec \"${INFINITO_SRC_DIR}/scripts/docker/entry.sh\" \"$@\"", "--"]

# IMPORTANT: default to systemd as PID 1
CMD ["/sbin/init"]
