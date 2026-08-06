# Runtime image for Postmarks (Node.js bookmarking app), built from a clone of
# upstream.
#
# The build stage patches in a trusted-header SSO bridge, gated at runtime on
# PROXY_HEADER_SSO, and the final stage carries the whole application directory
# over so no packages are refetched at start.
ARG NODE_BASE
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

COPY header_auth.js /app/src/sso-header-auth.js
COPY patch_server.js /app/sso-patch-server.js
RUN node /app/sso-patch-server.js /app/server.js && rm -f /app/sso-patch-server.js

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
