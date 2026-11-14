ARG PROVIDER_BASE_IMAGE
ARG PROVIDER_BASE_VERSION
FROM ${PROVIDER_BASE_IMAGE}:${PROVIDER_BASE_VERSION}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

ARG PROVIDER_UID
RUN groupadd --system --gid "${PROVIDER_UID}" provider \
 && useradd --system --uid "${PROVIDER_UID}" --gid provider --home-dir /app --shell /usr/sbin/nologin provider

WORKDIR /app

COPY provider ./provider

USER provider

HEALTHCHECK --interval=2m --timeout=5s --retries=3 --start-period=10m --start-interval=5s \
    CMD ["python", "-m", "provider", "health", "--config", "/run/secrets/provider.json"]

CMD ["python", "-m", "provider", "serve", "--config", "/run/secrets/provider.json"]
