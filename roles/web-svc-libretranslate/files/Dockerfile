ARG LIBRETRANSLATE_IMAGE
ARG LIBRETRANSLATE_VERSION
FROM ${LIBRETRANSLATE_IMAGE}:${LIBRETRANSLATE_VERSION}

COPY prefetch_models.py scripts/prefetch_models.py

ARG LIBRETRANSLATE_LOAD_ONLY
RUN if [ -n "${LIBRETRANSLATE_LOAD_ONLY}" ]; then \
      set -- --load_only_lang_codes "${LIBRETRANSLATE_LOAD_ONLY}"; \
    fi; \
    ./venv/bin/python scripts/prefetch_models.py "$@" \
    && ./venv/bin/python scripts/install_models.py "$@"
