ARG SIMPLEICONS_IMAGE
ARG SIMPLEICONS_VERSION
FROM ${SIMPLEICONS_IMAGE}:${SIMPLEICONS_VERSION} AS builder

WORKDIR /app
COPY ./config/package*.json ./

RUN npm install

ARG container_port
FROM ${SIMPLEICONS_IMAGE}:${SIMPLEICONS_VERSION}

RUN rm -rf /var/lib/apt/lists/* \
  && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /app/node_modules ./node_modules
COPY ./config/server.js .

EXPOSE ${container_port}

CMD ["node", "server.js"]
