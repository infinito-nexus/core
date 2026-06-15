ARG BASEROW_IMAGE
ARG BASEROW_VERSION
FROM ${BASEROW_IMAGE}:${BASEROW_VERSION}

COPY infinito_sso.py /baserow/backend/src/baserow/infinito_sso.py
COPY settings_patch.py /tmp/infinito_baserow_settings_patch.py
RUN cat /tmp/infinito_baserow_settings_patch.py >> /baserow/backend/src/baserow/config/urls.py
