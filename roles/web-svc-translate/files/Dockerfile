ARG TRANSLATE_BASE_IMAGE
ARG TRANSLATE_BASE_VERSION
FROM ${TRANSLATE_BASE_IMAGE}:${TRANSLATE_BASE_VERSION}

ARG TRANSLATE_PORT

COPY package-frontend-ca.crt /opt/package-frontend-ca.crt
COPY package-frontend-ca.sh /usr/local/bin/package-frontend-ca.sh
RUN /usr/local/bin/package-frontend-ca.sh

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY python/translate_gateway /app/translate_gateway
COPY python/infinito_decider /app/infinito_decider

RUN adduser --system --no-create-home --disabled-login translate
USER translate

EXPOSE ${TRANSLATE_PORT}
CMD ["sh", "-c", "exec uvicorn translate_gateway.asgi:app --host 0.0.0.0 --port \"${TRANSLATE_PORT}\""]
