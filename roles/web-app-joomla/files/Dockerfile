ARG JOOMLA_IMAGE
ARG JOOMLA_VERSION
ARG JOOMLA_ENTRYPOINT_SCRIPT_HOST_REL
ARG JOOMLA_ENTRYPOINT_SCRIPT_DOCKER
FROM ${JOOMLA_IMAGE}:${JOOMLA_VERSION}
ARG JOOMLA_ENTRYPOINT_SCRIPT_HOST_REL
ARG JOOMLA_ENTRYPOINT_SCRIPT_DOCKER

RUN rm -rf /var/lib/apt/lists/* \
    && apt-get update \
    && apt-get install -y --no-install-recommends git unzip curl ca-certificates \
    && curl --connect-timeout 5 --max-time 120 -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer \
    && rm -rf /var/lib/apt/lists/*

COPY ${JOOMLA_ENTRYPOINT_SCRIPT_HOST_REL} ${JOOMLA_ENTRYPOINT_SCRIPT_DOCKER}
RUN chmod +x "${JOOMLA_ENTRYPOINT_SCRIPT_DOCKER}" \
    && ln -sf "${JOOMLA_ENTRYPOINT_SCRIPT_DOCKER}" /usr/local/bin/entrypoint-joomla

ENTRYPOINT ["/usr/local/bin/entrypoint-joomla"]
CMD ["apache2-foreground"]
