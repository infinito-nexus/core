ARG NODE_BASE
FROM ${NODE_BASE} AS build

ARG ATMO_REPO_URL
ARG ATMO_REF
ARG ATMO_SIGNUP_PDS

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git init -q . && \
    git remote add origin "${ATMO_REPO_URL}" && \
    git fetch -q --depth=1 origin "${ATMO_REF}" && \
    git checkout -q --detach FETCH_HEAD && \
    rm -rf .git

RUN npm install -g --no-fund --no-audit "$(node -p "require('./package.json').packageManager")" && \
    pnpm install --frozen-lockfile

RUN settings=apps/web/src/lib/atproto/settings.ts && \
    grep -qx "export const ALLOW_SIGNUP = true;" "${settings}" && \
    grep -q "production: 'https://selfhosted.social/'" "${settings}" && \
    if [ -n "${ATMO_SIGNUP_PDS}" ]; then \
      sed -i "s|production: 'https://selfhosted.social/'|production: '${ATMO_SIGNUP_PDS}'|" "${settings}"; \
    else \
      sed -i "s|^export const ALLOW_SIGNUP = true;$|export const ALLOW_SIGNUP = false;|" "${settings}"; \
    fi

RUN pnpm --filter web build

FROM ${NODE_BASE}

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    ca-certificates python3 && \
    rm -rf /var/lib/apt/lists/*

COPY --from=build /app /app
COPY cron.py bridge.py /opt/atmo/
COPY atmo_bridge/ /opt/atmo/atmo_bridge/

ARG ATMO_DATA_DIR
ARG ATMO_BRIDGE_STATE_DIR
RUN mkdir -p "${ATMO_DATA_DIR}" "${ATMO_BRIDGE_STATE_DIR}" && \
    chown -R node:node /app/apps/web "${ATMO_DATA_DIR}" "${ATMO_BRIDGE_STATE_DIR}"

ENV WRANGLER_SEND_METRICS=false
USER node
WORKDIR /app/apps/web
