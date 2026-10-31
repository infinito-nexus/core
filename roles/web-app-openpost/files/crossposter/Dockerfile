ARG CROSSPOSTER_BASE_IMAGE
ARG CROSSPOSTER_BASE_VERSION
FROM ${CROSSPOSTER_BASE_IMAGE}:${CROSSPOSTER_BASE_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG CROSSPOSTER_UID
RUN groupadd --system --gid "${CROSSPOSTER_UID}" crossposter \
 && useradd --system --uid "${CROSSPOSTER_UID}" --gid crossposter --home-dir /app --shell /usr/sbin/nologin crossposter

WORKDIR /app

RUN pip install --no-cache-dir "psycopg[binary]==3.2.10" "pillow==11.3.0"

COPY crossposter ./crossposter

USER crossposter

HEALTHCHECK --interval=2m --timeout=5s --retries=3 --start-period=10m --start-interval=5s \
    CMD ["python", "-m", "crossposter", "health", "--config", "/config/crossposter.json"]

CMD ["python", "-m", "crossposter", "run", "--config", "/config/crossposter.json"]
