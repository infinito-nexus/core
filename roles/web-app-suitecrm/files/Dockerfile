ARG SUITECRM_BASE_IMAGE
ARG SUITECRM_BASE_VERSION

FROM ${SUITECRM_BASE_IMAGE}:${SUITECRM_BASE_VERSION} AS base

ARG SUITECRM_APP_DIR

RUN rm -rf /var/lib/apt/lists/* \
  && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y \
      git \
      wget \
      unzip \
      libpng-dev \
      libzip-dev \
      libicu-dev \
      libonig-dev \
      libxml2-dev \
      libldap2-dev \
  && docker-php-ext-configure ldap --with-libdir=lib/x86_64-linux-gnu \
  && docker-php-ext-install \
      pdo \
      pdo_mysql \
      mysqli \
      gd \
      zip \
      intl \
      mbstring \
      soap \
      opcache \
      ldap \
  && rm -rf /var/lib/apt/lists/*

RUN { \
      echo 'file_uploads = On'; \
      echo 'upload_max_filesize = 32M'; \
      echo 'post_max_size = 32M'; \
      echo 'memory_limit = 512M'; \
   } > /usr/local/etc/php/conf.d/suitecrm-upload.ini

RUN a2enmod rewrite headers

RUN sed -ri 's!'"${SUITECRM_APP_DIR}"'!'"${SUITECRM_APP_DIR}"'/public!g' \
      /etc/apache2/sites-available/000-default.conf \
      /etc/apache2/apache2.conf


FROM base AS builder

ARG SUITECRM_APP_VERSION
ARG SUITECRM_APP_DIR
ARG SUITECRM_LDAP_EXTENSION_DIR

WORKDIR ${SUITECRM_APP_DIR}

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

RUN set -eux; \
    SUITECRM_TAG="v${SUITECRM_APP_VERSION}"; \
    wget -qO /tmp/suitecrm.tar.gz \
      "https://github.com/SuiteCRM/SuiteCRM-Core/archive/refs/tags/${SUITECRM_TAG}.tar.gz"; \
    tar --strip-components=1 -xzf /tmp/suitecrm.tar.gz -C "${SUITECRM_APP_DIR}"; \
    rm /tmp/suitecrm.tar.gz; \
    chmod +x bin/console

RUN set -eux; \
    composer install \
      --prefer-dist \
      --no-interaction \
      --optimize-autoloader \
      --no-scripts

WORKDIR ${SUITECRM_APP_DIR}/public/legacy

RUN set -eux; \
    if [ -f composer.json ]; then \
      composer install --no-dev --prefer-dist --no-interaction --optimize-autoloader --no-scripts; \
    fi

WORKDIR ${SUITECRM_APP_DIR}

RUN rm -rf /var/lib/apt/lists/* \
 && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y nodejs npm \
 && corepack enable && corepack prepare yarn@4.5.1 --activate \
 && rm -rf /var/lib/apt/lists/*

RUN yarn install --immutable \
 && yarn merge-angular-json \
 && yarn build \
 && rm -rf .angular/cache .yarn/cache .yarn/unplugged .yarn/install-state.gz \
 && rm -rf node_modules

RUN set -eux; \
    php ./vendor/bin/pscss -s compressed \
      public/legacy/themes/suite8/css/Dawn/style.scss \
      > public/legacy/themes/suite8/css/Dawn/style.css

RUN set -eux; \
    composer install \
      --no-dev \
      --prefer-dist \
      --no-interaction \
      --optimize-autoloader \
      --no-scripts

RUN set -eux; \
    mkdir -p "${SUITECRM_LDAP_EXTENSION_DIR}"; \
    for d in cache public/upload public/legacy/upload public/legacy/cache tmp; do \
      mkdir -p "${SUITECRM_APP_DIR}/${d}"; \
      chmod -R 775 "${SUITECRM_APP_DIR}/${d}"; \
    done


FROM base

ARG SUITECRM_ENTRYPOINT_SCRIPT_HOST_REL
ARG SUITECRM_ENTRYPOINT_SCRIPT_DOCKER
ARG SUITECRM_APP_DIR
ARG SUITECRM_SEED_DIR
ARG SUITECRM_WEB_USER
ARG SUITECRM_WEB_GROUP
ENV SUITECRM_APP_DIR=${SUITECRM_APP_DIR} \
    SUITECRM_SEED_DIR=${SUITECRM_SEED_DIR} \
    SUITECRM_WEB_USER=${SUITECRM_WEB_USER} \
    SUITECRM_WEB_GROUP=${SUITECRM_WEB_GROUP}

COPY --from=builder --chown=${SUITECRM_WEB_USER}:${SUITECRM_WEB_GROUP} ${SUITECRM_APP_DIR} ${SUITECRM_SEED_DIR}

RUN set -eux; \
    mkdir -p "${SUITECRM_APP_DIR}"; \
    chown "${SUITECRM_WEB_USER}:${SUITECRM_WEB_GROUP}" "${SUITECRM_APP_DIR}"

WORKDIR ${SUITECRM_APP_DIR}

COPY ${SUITECRM_ENTRYPOINT_SCRIPT_HOST_REL} ${SUITECRM_ENTRYPOINT_SCRIPT_DOCKER}
RUN chmod +x ${SUITECRM_ENTRYPOINT_SCRIPT_DOCKER} \
    && ln -sf "${SUITECRM_ENTRYPOINT_SCRIPT_DOCKER}" /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["apache2-foreground"]
