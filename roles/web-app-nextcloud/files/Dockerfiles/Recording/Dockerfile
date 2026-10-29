ARG RECORDING_BASE_IMAGE
ARG RECORDING_BASE_VERSION
FROM ${RECORDING_BASE_IMAGE}:${RECORDING_BASE_VERSION}
ARG RECORDING_REPOSITORY
ARG RECORDING_REF
ARG RECORDING_USER_ID
ARG RECORDING_DIRECTORY
ARG RECORDING_CONFIG_DIRECTORY

RUN set -ex; \
    apk upgrade --no-cache -a; \
    apk add --no-cache \
        ca-certificates \
        tzdata \
        bash \
        xvfb \
        ffmpeg \
        firefox \
        font-noto-all \
        font-noto-cjk \
        font-noto-cjk-extra \
        bind-tools \
        netcat-openbsd \
        git \
        shadow \
        pulseaudio \
        build-base \
        linux-headers \
        geckodriver; \
    useradd -d "${RECORDING_DIRECTORY}" --system recording -u "${RECORDING_USER_ID}"; \
    git clone --recursive "${RECORDING_REPOSITORY}" --depth=1 --single-branch --branch "${RECORDING_REF}" /src; \
    python3 -m pip install --no-cache-dir /src; \
    rm -rf /src; \
    mkdir -p "${RECORDING_CONFIG_DIRECTORY}"; \
    chown recording:recording -R "${RECORDING_DIRECTORY}"; \
    apk del --no-cache \
        git \
        shadow \
        build-base \
        linux-headers

ARG RECORDING_CA_CERT
RUN if [ -n "${RECORDING_CA_CERT}" ]; then \
      mkdir -p /etc/firefox/policies \
      && printf '{"policies":{"Certificates":{"Install":["%s"]}}}\n' "${RECORDING_CA_CERT}" > /etc/firefox/policies/policies.json; \
    fi

WORKDIR ${RECORDING_DIRECTORY}
USER ${RECORDING_USER_ID}
ENTRYPOINT ["python", "-m", "nextcloud.talk.recording"]
