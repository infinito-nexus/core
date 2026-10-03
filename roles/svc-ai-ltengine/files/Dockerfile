ARG LTENGINE_BUILDER_IMAGE
ARG LTENGINE_BUILDER_VERSION
ARG LTENGINE_BASE_IMAGE
ARG LTENGINE_BASE_VERSION

FROM ${LTENGINE_BUILDER_IMAGE}:${LTENGINE_BUILDER_VERSION} AS build

ARG LTENGINE_REPOSITORY
ARG LTENGINE_REF

RUN rm -rf /var/lib/apt/lists/* \
  && apt-get -o Acquire::Retries=3 update \
  && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    build-essential \
    ca-certificates \
    clang \
    cmake \
    git \
    libssl-dev \
    pkg-config \
  && rm -rf /var/lib/apt/lists/*

COPY package-frontend-ca.crt /opt/package-frontend-ca.crt
COPY package-frontend-ca.sh /usr/local/bin/package-frontend-ca.sh
RUN /usr/local/bin/package-frontend-ca.sh

WORKDIR /build
RUN git init -q . \
  && git remote add origin "${LTENGINE_REPOSITORY}" \
  && git fetch -q --depth=1 origin "${LTENGINE_REF}" \
  && git checkout -q --detach FETCH_HEAD

RUN cargo build --locked --release -p ltengine \
  && install -Dm755 -s target/release/ltengine /out/ltengine

FROM ${LTENGINE_BASE_IMAGE}:${LTENGINE_BASE_VERSION}

ARG LTENGINE_MODELS_DIR

RUN rm -rf /var/lib/apt/lists/* \
  && apt-get -o Acquire::Retries=3 update \
  && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    ca-certificates \
    libgomp1 \
    libssl3 \
  && rm -rf /var/lib/apt/lists/*

RUN useradd --system --no-create-home --shell /usr/sbin/nologin ltengine \
  && mkdir -p "${LTENGINE_MODELS_DIR}" \
  && chown ltengine:ltengine "${LTENGINE_MODELS_DIR}"

COPY --from=build /out/ltengine /usr/local/bin/ltengine

USER ltengine
CMD ["sh", "-c", "exec ltengine --host \"${LTENGINE_HOST}\" --port \"${LTENGINE_PORT}\" --model \"${LTENGINE_MODEL}\" --char-limit \"${LTENGINE_CHAR_LIMIT}\""]
