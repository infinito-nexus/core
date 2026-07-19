ARG ODOO_IMAGE
ARG ODOO_VERSION
ARG ODOO_ENTRYPOINT_SCRIPT_HOST_REL
ARG ODOO_ENTRYPOINT_SCRIPT_DOCKER

FROM ${ODOO_IMAGE}:${ODOO_VERSION}
ARG ODOO_ENTRYPOINT_SCRIPT_HOST_REL
ARG ODOO_ENTRYPOINT_SCRIPT_DOCKER

USER root

RUN rm -rf /var/lib/apt/lists/* \
    && apt-get update && apt-get install -y --no-install-recommends \
    libxml2-dev \
    libxmlsec1-dev \
    libxmlsec1-openssl \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir --break-system-packages \
    python3-saml==1.16.0 \
    oauthlib==3.2.2 \
    requests-oauthlib==2.0.0 \
    PyJWT==2.9.0

RUN mkdir -p /var/log/odoo && \
    chown -R odoo:odoo /var/log/odoo

COPY volumes/addons/ /mnt/custom-addons/

COPY ${ODOO_ENTRYPOINT_SCRIPT_HOST_REL} ${ODOO_ENTRYPOINT_SCRIPT_DOCKER}
RUN chmod +x "${ODOO_ENTRYPOINT_SCRIPT_DOCKER}" \
    && ln -sf "${ODOO_ENTRYPOINT_SCRIPT_DOCKER}" /usr/local/bin/entrypoint-odoo

USER odoo

ENTRYPOINT ["/usr/local/bin/entrypoint-odoo"]
CMD ["odoo"]
