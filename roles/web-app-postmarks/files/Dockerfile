# Runtime image for Postmarks (Node.js bookmarking app) with a build
# step that clones upstream from GitHub.
ARG NODE_BASE="node:26-bookworm"
FROM ${NODE_BASE} AS build

ARG POSTMARKS_REPO_URL
ARG POSTMARKS_REF

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    git ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth=1 --branch "${POSTMARKS_REF}" "${POSTMARKS_REPO_URL}" ./
RUN npm install --no-fund --no-audit --omit=dev

# Exception: trusted-header SSO bridge patched into upstream's server.js at
# build time; it self-gates at runtime on PROXY_HEADER_SSO.
COPY header_auth.js /app/src/sso-header-auth.js
COPY patch_server.js /app/sso-patch-server.js
RUN node /app/sso-patch-server.js /app/server.js && rm -f /app/sso-patch-server.js

# Exception: the final stage must carry over the application directory and the
# npm install artefacts; without them node_modules is missing at runtime.
FROM ${NODE_BASE}

ARG CONTAINER_PORT
ENV PORT=${CONTAINER_PORT}
ENV NODE_ENV=production

WORKDIR /app
COPY --from=build /app /app

RUN useradd -r -m -d /nonroot appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE ${PORT}
CMD ["node", "server.js"]
