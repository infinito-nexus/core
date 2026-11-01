ARG SEMAPHORE_SERVER_IMAGE
ARG SEMAPHORE_RUNNER_BASE_IMAGE
FROM ${SEMAPHORE_SERVER_IMAGE} AS semaphore

FROM ${SEMAPHORE_RUNNER_BASE_IMAGE}

ARG SEMAPHORE_RUNNER_USER
ARG SEMAPHORE_RUNNER_UID
ARG SEMAPHORE_RUNNER_GID
ARG SEMAPHORE_RUNNER_REPOSITORY
ARG SEMAPHORE_RUNNER_TMP
ARG SEMAPHORE_RUNNER_DOCKERFILE_DIGEST
ARG SEMAPHORE_RUNNER_REPOSITORY_DIGEST
ARG SEMAPHORE_RUNNER_INPUTS_DIGEST

COPY --from=semaphore /usr/local/bin/semaphore /usr/local/bin/semaphore

RUN groupadd --gid "${SEMAPHORE_RUNNER_GID}" "${SEMAPHORE_RUNNER_USER}" \
    && useradd --uid "${SEMAPHORE_RUNNER_UID}" --gid "${SEMAPHORE_RUNNER_GID}" \
        --create-home --shell /bin/bash "${SEMAPHORE_RUNNER_USER}" \
    && ln -s "${INFINITO_SRC_DIR}/roles/web-app-semaphore/files/shell/repository" "${SEMAPHORE_RUNNER_REPOSITORY}" \
    && test -f "${SEMAPHORE_RUNNER_REPOSITORY}/app-control.sh" \
    && test -f "${SEMAPHORE_RUNNER_REPOSITORY}/deploy.sh" \
    && test -d /root/.ansible/collections/ansible_collections \
    && install -d -m 0755 /usr/share/ansible/collections \
    && cp -a /root/.ansible/collections/. /usr/share/ansible/collections/ \
    && chmod -R a+rX /usr/share/ansible/collections \
    && install -d -o "${SEMAPHORE_RUNNER_UID}" -g "${SEMAPHORE_RUNNER_GID}" -m 0700 "${SEMAPHORE_RUNNER_TMP}"

# nocheck: healthcheck-timing-override  NONE drops the systemd probe of the Infinito.Nexus base image; the runner runs no systemd and opens no port
HEALTHCHECK NONE
STOPSIGNAL SIGTERM
LABEL nexus.infinito.semaphore.runner.dockerfile="${SEMAPHORE_RUNNER_DOCKERFILE_DIGEST}" \
      nexus.infinito.semaphore.runner.repository="${SEMAPHORE_RUNNER_REPOSITORY_DIGEST}" \
      nexus.infinito.semaphore.runner.inputs="${SEMAPHORE_RUNNER_INPUTS_DIGEST}"
USER ${SEMAPHORE_RUNNER_UID}:${SEMAPHORE_RUNNER_GID}
WORKDIR /home/${SEMAPHORE_RUNNER_USER}

ENTRYPOINT ["/usr/local/bin/semaphore", "runner", "start", "--no-config"]
CMD []
