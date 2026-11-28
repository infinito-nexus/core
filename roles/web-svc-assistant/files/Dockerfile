ARG ASSISTANT_IMAGE
ARG ASSISTANT_VERSION
FROM ${ASSISTANT_IMAGE}:${ASSISTANT_VERSION}

ARG ASSISTANT_PORT

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY python/assistant /app/assistant
COPY python/utils /app/utils

ENV PYTHONPATH=/app

RUN adduser --system --no-create-home --disabled-login assistant
USER assistant

EXPOSE ${ASSISTANT_PORT}
CMD ["sh", "-c", "exec uvicorn assistant.asgi:app --host 0.0.0.0 --port \"${ASSISTANT_PORT}\" --no-access-log"]
