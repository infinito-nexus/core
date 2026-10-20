ARG NLLB_BASE_IMAGE
ARG NLLB_BASE_VERSION
FROM ${NLLB_BASE_IMAGE}:${NLLB_BASE_VERSION}

ARG NLLB_GPU
ARG NLLB_MODELS_DIR

COPY package-frontend-ca.crt /opt/package-frontend-ca.crt
COPY package-frontend-ca.sh /usr/local/bin/package-frontend-ca.sh
RUN /usr/local/bin/package-frontend-ca.sh

COPY build.sh /usr/local/bin/build.sh
RUN bash /usr/local/bin/build.sh

RUN useradd --system --no-create-home --shell /usr/sbin/nologin nllb \
  && mkdir -p "${NLLB_MODELS_DIR}" \
  && chown nllb:nllb "${NLLB_MODELS_DIR}"

WORKDIR /app
COPY server.py /app/server.py

USER nllb
CMD ["sh", "-c", "exec uvicorn server:app --app-dir /app --host \"${NLLB_HOST}\" --port \"${NLLB_PORT}\""]
