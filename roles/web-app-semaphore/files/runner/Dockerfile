ARG SEMAPHORE_SERVER_IMAGE
ARG SEMAPHORE_RUNNER_BASE_IMAGE
FROM ${SEMAPHORE_SERVER_IMAGE} AS semaphore

FROM scratch AS export-tools

ARG SEMAPHORE_AGE_URL
ARG SEMAPHORE_KEEPASSXC_URL

ADD ${SEMAPHORE_AGE_URL} /age.tar.gz
ADD ${SEMAPHORE_KEEPASSXC_URL} /keepassxc.AppImage

FROM ${SEMAPHORE_RUNNER_BASE_IMAGE} AS opentofu

ARG SEMAPHORE_OPENTOFU_URL
ARG SEMAPHORE_OPENTOFU_SHA256
ARG SEMAPHORE_OPENTOFU_PLATFORM

ADD ${SEMAPHORE_OPENTOFU_URL} /tmp/opentofu.tar.gz
RUN bash "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/shell/opentofu/build.sh" \
        install /tmp/opentofu.tar.gz "${SEMAPHORE_OPENTOFU_SHA256}" /usr/local/bin/tofu \
    && rm /tmp/opentofu.tar.gz \
    && bash "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/shell/opentofu/build.sh" \
        mirror "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/opentofu" "${SEMAPHORE_OPENTOFU_PLATFORM}"

FROM opentofu AS opentofu-check

RUN --network=none bash "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/shell/opentofu/build.sh" \
        validate "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/opentofu" \
        > /usr/local/share/opentofu/validated

FROM ${SEMAPHORE_RUNNER_BASE_IMAGE}

ARG SEMAPHORE_RUNNER_BASE_IMAGE
ARG SEMAPHORE_RUNNER_USER
ARG SEMAPHORE_RUNNER_UID
ARG SEMAPHORE_RUNNER_GID
ARG SEMAPHORE_RUNNER_REPOSITORY
ARG SEMAPHORE_RUNNER_TMP
ARG SEMAPHORE_RUNNER_DOCKERFILE_DIGEST
ARG SEMAPHORE_RUNNER_REPOSITORY_DIGEST
ARG SEMAPHORE_RUNNER_INPUTS_DIGEST
ARG SEMAPHORE_AGE_SHA256
ARG SEMAPHORE_KEEPASSXC_SHA256

COPY --from=semaphore /usr/local/bin/semaphore /usr/local/bin/semaphore
COPY --from=opentofu /usr/local/bin/tofu /usr/local/bin/tofu
COPY --from=opentofu /usr/local/share/opentofu/providers /usr/local/share/opentofu/providers
COPY --from=opentofu-check /usr/local/share/opentofu/validated /usr/local/share/opentofu/validated

RUN --mount=type=bind,from=export-tools,target=/tmp/export-tools \
    bash "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/shell/opentofu/build.sh" runtime \
    && bash "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/shell/opentofu/build.sh" \
        install /tmp/export-tools/age.tar.gz "${SEMAPHORE_AGE_SHA256}" /usr/local/bin/age \
    && bash "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/shell/opentofu/build.sh" \
        install /tmp/export-tools/keepassxc.AppImage "${SEMAPHORE_KEEPASSXC_SHA256}" /usr/local/bin/keepassxc-cli

RUN groupadd --gid "${SEMAPHORE_RUNNER_GID}" "${SEMAPHORE_RUNNER_USER}" \
    && useradd --uid "${SEMAPHORE_RUNNER_UID}" --gid "${SEMAPHORE_RUNNER_GID}" \
        --create-home --shell /bin/bash "${SEMAPHORE_RUNNER_USER}" \
    && ln -s "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/shell/repository" "${SEMAPHORE_RUNNER_REPOSITORY}" \
    && test -f "${SEMAPHORE_RUNNER_REPOSITORY}/app-control.sh" \
    && test -f "${SEMAPHORE_RUNNER_REPOSITORY}/deploy.sh" \
    && install -d -m 0755 /etc/ssh/ssh_config.d \
    && test -f "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/python/egress_connect.py" \
    && printf 'Match exec "printenv EGRESS_PROXY >/dev/null"\n    ProxyCommand python3 %s/roles/web-app-semaphore/files/python/egress_connect.py %%h %%p\n' "${INFINITO_SRC_DIR}" \
        > /etc/ssh/ssh_config.d/50-egress.conf \
    && test -d /root/.ansible/collections/ansible_collections \
    && install -d -m 0755 /usr/share/ansible/collections \
    && cp -a /root/.ansible/collections/. /usr/share/ansible/collections/ \
    && chmod -R a+rX /usr/share/ansible/collections \
    && install -d -o "${SEMAPHORE_RUNNER_UID}" -g "${SEMAPHORE_RUNNER_GID}" -m 0700 "${SEMAPHORE_RUNNER_TMP}"

RUN install -d -m 0755 /usr/local/share/semaphore-runner \
    && awk -F '"' '/^\[/ { section = $0 } section == "[project]" && /^version[[:space:]]*=/ { print $2; exit }' \
        "${INFINITO_SRC_DIR}/pyproject.toml" > /usr/local/share/semaphore-runner/core-version \
    && test -s /usr/local/share/semaphore-runner/core-version \
    && if grep -qs '"digest-file"' "${INFINITO_SRC_DIR}/utils/platform_monitoring.py"; then \
        python3 -I "${INFINITO_SRC_DIR}/utils/platform_monitoring.py" digest-file "${INFINITO_SRC_DIR}" \
        > /usr/local/share/semaphore-runner/federation-digest-file \
        && test -s /usr/local/share/semaphore-runner/federation-digest-file; \
    else \
        : > /usr/local/share/semaphore-runner/federation-digest-file; \
    fi \
    && install -m 0644 "${INFINITO_SRC_DIR}/CHANGELOG.md" /usr/local/share/semaphore-runner/CHANGELOG.md

ARG SEMAPHORE_SANDBOX_ENTRYPOINT
RUN command -v setpriv \
    && test -f "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/python/sandbox/spawner.py" \
    && test -f "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/python/provision/sandbox.py" \
    && install -d -m 0755 "$(dirname "${SEMAPHORE_SANDBOX_ENTRYPOINT}")" \
    && printf '#!/bin/sh\nexec python3 -E -s %s/roles/web-app-semaphore/files/python/sandbox/spawner.py serve /usr/local/bin/semaphore runner start --no-config "$@"\n' "${INFINITO_SRC_DIR}" \
        > "${SEMAPHORE_SANDBOX_ENTRYPOINT}" \
    && chmod 0755 "${SEMAPHORE_SANDBOX_ENTRYPOINT}"

# nocheck: healthcheck-timing-override  NONE drops the systemd probe of the Infinito.Nexus base image; the runner runs no systemd and opens no port
HEALTHCHECK NONE
STOPSIGNAL SIGTERM
LABEL nexus.infinito.semaphore.runner.base="${SEMAPHORE_RUNNER_BASE_IMAGE}" \
      nexus.infinito.semaphore.runner.dockerfile="${SEMAPHORE_RUNNER_DOCKERFILE_DIGEST}" \
      nexus.infinito.semaphore.runner.repository="${SEMAPHORE_RUNNER_REPOSITORY_DIGEST}" \
      nexus.infinito.semaphore.runner.inputs="${SEMAPHORE_RUNNER_INPUTS_DIGEST}"
USER ${SEMAPHORE_RUNNER_UID}:${SEMAPHORE_RUNNER_GID}
WORKDIR /home/${SEMAPHORE_RUNNER_USER}

ENTRYPOINT ["/usr/local/bin/semaphore", "runner", "start", "--no-config"]
CMD []
