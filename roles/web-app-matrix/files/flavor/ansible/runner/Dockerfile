ARG MATRIX_MDAD_RUNNER_BASE_IMAGE
ARG MATRIX_MDAD_RUNNER_BASE_VERSION
ARG MATRIX_MDAD_RUNNER_DOCKER_CLI_IMAGE
ARG MATRIX_MDAD_RUNNER_DOCKER_CLI_VERSION
FROM ${MATRIX_MDAD_RUNNER_DOCKER_CLI_IMAGE}:${MATRIX_MDAD_RUNNER_DOCKER_CLI_VERSION} AS docker-cli

FROM ${MATRIX_MDAD_RUNNER_BASE_IMAGE}:${MATRIX_MDAD_RUNNER_BASE_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/ansible \
    PATH=/opt/ansible/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    container=docker

COPY --from=docker-cli /usr/local/bin/docker /usr/bin/docker
COPY --from=docker-cli /usr/local/libexec/docker/cli-plugins/ /usr/local/libexec/docker/cli-plugins/

RUN rm -rf /var/lib/apt/lists/* \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates \
      dbus \
      docker.io \
      fuse-overlayfs \
      git \
      iptables \
      openssh-client \
      python3-venv \
      systemd \
      systemd-sysv \
 && rm -rf /var/lib/apt/lists/*

RUN systemd-machine-id-setup || true

RUN systemctl mask \
      sys-kernel-debug.mount \
      sys-fs-fuse-connections.mount \
      sys-kernel-config.mount \
      systemd-logind.service \
      systemd-firstboot.service \
      systemd-machine-id-commit.service \
      systemd-udevd.service \
      systemd-udev-trigger.service \
      systemd-udev-settle.service \
      systemd-modules-load.service \
      systemd-tmpfiles-setup-dev.service \
      systemd-remount-fs.service \
      kmod-static-nodes.service \
      console-getty.service \
      getty.target \
      getty@.service

RUN python3 -m venv "$VIRTUAL_ENV" \
 && "$VIRTUAL_ENV/bin/pip" install --no-cache-dir \
      'ansible-core>=2.18,<2.19' \
      docker \
      jmespath \
      netaddr \
      passlib \
      pyyaml \
      requests

RUN ansible-galaxy collection install \
      community.docker \
      community.general \
      ansible.posix

COPY daemon.json /etc/docker/daemon.json
COPY bootstrap.sh /usr/local/bin/matrix-mdad-bootstrap
COPY bootstrap.service /etc/systemd/system/matrix-mdad-bootstrap.service
RUN chmod 0755 /usr/local/bin/matrix-mdad-bootstrap \
 && systemctl enable containerd.service docker.service matrix-mdad-bootstrap.service

WORKDIR /mdad
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
