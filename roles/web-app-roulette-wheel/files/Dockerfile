ARG ROULETTE_IMAGE
ARG ROULETTE_VERSION
FROM ${ROULETTE_IMAGE}:${ROULETTE_VERSION}

RUN rm -rf /var/lib/apt/lists/* \
  && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ARG ROULETTE_WHEEL_APP_REL
COPY ./${ROULETTE_WHEEL_APP_REL}/package.json ./${ROULETTE_WHEEL_APP_REL}/package-lock.json ./
RUN npm ci
COPY ./${ROULETTE_WHEEL_APP_REL}/ ./
RUN npm run build
CMD ["npm", "run", "start"]
