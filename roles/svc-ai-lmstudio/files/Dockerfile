ARG LMSTUDIO_IMAGE
ARG LMSTUDIO_VERSION
FROM ${LMSTUDIO_IMAGE}:${LMSTUDIO_VERSION}

ARG LMSTUDIO_APP_VERSION
ARG LMSTUDIO_PORT

ENV LMSTUDIO_PORT=${LMSTUDIO_PORT} \
    PATH=/app/.bundle:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

RUN rm -rf /var/lib/apt/lists/* \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        ca-certificates \
        curl \
        libatomic1 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY install.sh /tmp/install.sh
RUN bash /tmp/install.sh "${LMSTUDIO_APP_VERSION}" && rm /tmp/install.sh

COPY daemon-run.sh /app/daemon-run.sh
RUN chmod 0755 /app/daemon-run.sh

EXPOSE ${LMSTUDIO_PORT}

ENTRYPOINT ["/app/daemon-run.sh"]
