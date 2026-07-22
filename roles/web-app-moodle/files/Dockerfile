# Self-built Moodle image. See docs/requirements/015-moodle-self-built.md.
#
# Static Dockerfile — all dynamic values flow in as build ARGs from
# compose.yml.j2, which derives them from roles/web-app-moodle/vars/main.yml.
# That vars file is the single source of truth for:
#   - container paths    (MOODLE_CODE_DIR, MOODLE_DATA_DIR, MOODLE_SOURCE_DIR,
#                         MOODLE_ENTRYPOINT_PATH)
#   - build-asset names  (MOODLE_BUILD_DIR, MOODLE_BUILD_FILES.*)
#
# The COPY src paths and the ENTRYPOINT JSON-array literal in this
# file MUST stay in sync with vars/main.yml because Docker does not
# expand ARG/ENV inside JSON-form ENTRYPOINT and only resolves COPY
# src against the build context. Treat the literals below as a
# locked-in contract — when you add or rename a build asset, update
# vars/main.yml first and propagate here.

ARG MOODLE_BASE_IMAGE
ARG MOODLE_BASE_TAG
FROM ${MOODLE_BASE_IMAGE}:${MOODLE_BASE_TAG}

ARG MOODLE_CODE_DIR
ARG MOODLE_DATA_DIR
ARG MOODLE_SOURCE_DIR
ARG MOODLE_RUNTIME_USER
ARG MOODLE_OIDC_ENABLED
ARG MOODLE_OIDC_PLUGIN_RELPATH
ARG MOODLE_RELEASE
ARG MOODLE_TARBALL_URL
ARG MOODLE_TARBALL_FILENAME
ARG MOODLE_VERSION_FILE
ARG MOODLE_AUTH_SUBDIR

ENV MOODLE_CODE_DIR=${MOODLE_CODE_DIR} \
    MOODLE_DATA_DIR=${MOODLE_DATA_DIR} \
    MOODLE_SOURCE_DIR=${MOODLE_SOURCE_DIR} \
    MOODLE_RUNTIME_USER=${MOODLE_RUNTIME_USER} \
    MOODLE_OIDC_PLUGIN_RELPATH=${MOODLE_OIDC_PLUGIN_RELPATH} \
    MOODLE_RELEASE=${MOODLE_RELEASE} \
    MOODLE_TARBALL_URL=${MOODLE_TARBALL_URL} \
    MOODLE_TARBALL_FILENAME=${MOODLE_TARBALL_FILENAME} \
    MOODLE_VERSION_FILE=${MOODLE_VERSION_FILE} \
    MOODLE_AUTH_SUBDIR=${MOODLE_AUTH_SUBDIR}

# hadolint ignore=DL3008
RUN rm -rf /var/lib/apt/lists/* \
 && apt-get -o Acquire::Retries=3 update \
 && DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
      ca-certificates \
      curl \
      file \
      gosu \
      jq \
      libfreetype6-dev \
      libicu-dev \
      libjpeg-dev \
      libldap2-dev \
      libonig-dev \
      libpng-dev \
      libpq-dev \
      libwebp-dev \
      libxml2-dev \
      libxslt1-dev \
      libzip-dev \
      msmtp \
      msmtp-mta \
      unzip \
 && rm -rf /var/lib/apt/lists/*

RUN docker-php-ext-configure gd --with-freetype --with-jpeg --with-webp \
 && docker-php-ext-configure intl \
 && docker-php-ext-configure ldap \
 && docker-php-ext-install -j"$(nproc)" \
      exif \
      gd \
      intl \
      ldap \
      mysqli \
      opcache \
      pgsql \
      pdo_mysql \
      pdo_pgsql \
      soap \
      xsl \
      zip

COPY build/php-conf/opcache-recommended.ini /usr/local/etc/php/conf.d/opcache-recommended.ini
COPY build/php-conf/moodle-runtime.ini      /usr/local/etc/php/conf.d/moodle-runtime.ini
COPY build/php-conf/zz-moodle-pool.conf     /usr/local/etc/php-fpm.d/zz-moodle-pool.conf

COPY build/install/moodle-source.sh /tmp/install-moodle-source.sh
RUN bash /tmp/install-moodle-source.sh && rm /tmp/install-moodle-source.sh

COPY build/install/auth-oidc.sh /tmp/install-auth-oidc.sh
RUN if [ "${MOODLE_OIDC_ENABLED}" = "1" ] || [ "${MOODLE_OIDC_ENABLED}" = "true" ]; then \
      bash /tmp/install-auth-oidc.sh; \
    fi \
 && rm /tmp/install-auth-oidc.sh

COPY build/config.php ${MOODLE_SOURCE_DIR}/config.php
RUN chown ${MOODLE_RUNTIME_USER}:${MOODLE_RUNTIME_USER} ${MOODLE_SOURCE_DIR}/config.php \
 && chmod 0640 ${MOODLE_SOURCE_DIR}/config.php

COPY build/moodle-entrypoint.sh /usr/local/bin/moodle-entrypoint.sh
RUN chmod 0755 /usr/local/bin/moodle-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/moodle-entrypoint.sh"]
CMD ["php-fpm"]
