ARG FLOWISE_BASE_IMAGE
ARG FLOWISE_BASE_TAG
FROM ${FLOWISE_BASE_IMAGE}:${FLOWISE_BASE_TAG}

ARG FLOWISE_VERSION
ARG FLOWISE_SQLITE_VERSION

RUN rm -rf /var/lib/apt/lists/* \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        chromium git python3 curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV PUPPETEER_SKIP_DOWNLOAD=true
ENV PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
ENV FLOWISE_HOME=/opt/flowise

WORKDIR ${FLOWISE_HOME}

RUN shim=/tmp/socket-timeout.cjs \
    && echo 'require("http").globalAgent.options.timeout=60000;require("https").globalAgent.options.timeout=60000' > "$shim" \
    && npm init -y > /dev/null \
    && npm pkg set "overrides.better-sqlite3=^${FLOWISE_SQLITE_VERSION}" \
    && NODE_OPTIONS=--require="$shim" npm install --omit=dev "flowise@${FLOWISE_VERSION}" \
    && rm -f "$shim" \
    && ln -s "${FLOWISE_HOME}/node_modules/.bin/flowise" /usr/local/bin/flowise \
    && chown -R node:node "${FLOWISE_HOME}"

USER node

ENTRYPOINT ["flowise", "start"]
