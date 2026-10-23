ARG LIBRETRANSLATE_IMAGE
ARG LIBRETRANSLATE_VERSION
FROM ${LIBRETRANSLATE_IMAGE}:${LIBRETRANSLATE_VERSION}

ARG APP_USER

USER root
COPY package-frontend-ca.crt /opt/package-frontend-ca.crt
COPY package-frontend-ca.sh /usr/local/bin/package-frontend-ca.sh
RUN /usr/local/bin/package-frontend-ca.sh
USER ${APP_USER}

COPY prefetch_models.py scripts/prefetch_models.py

ARG LIBRETRANSLATE_LOAD_ONLY
ARG LIBRETRANSLATE_DIRECTIONS
RUN if [ -n "${LIBRETRANSLATE_LOAD_ONLY}" ]; then \
      set -- --load_only_lang_codes "${LIBRETRANSLATE_LOAD_ONLY}"; \
    fi; \
    PYTHONPATH=. REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
      ./venv/bin/python scripts/prefetch_models.py \
      --directions "${LIBRETRANSLATE_DIRECTIONS}" "$@"
