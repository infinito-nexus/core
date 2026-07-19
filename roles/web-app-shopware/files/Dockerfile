
ARG SHOPWARE_CONTAINER_IMAGE
ARG SHOPWARE_CONTAINER_VERSION
ARG SHOPWARE_PHP_IMAGE
ARG SHOPWARE_PHP_VERSION
FROM ${SHOPWARE_CONTAINER_IMAGE}:${SHOPWARE_CONTAINER_VERSION} AS builder
ENV COMPOSER_ALLOW_SUPERUSER=1 \
    COMPOSER_NO_INTERACTION=1 \
    COMPOSER_PROCESS_TIMEOUT=900

WORKDIR /app
ARG SHOPWARE_PKG_NAME
ARG SHOPWARE_PKG_VERSION
ARG SHOPWARE_COMPOSER_PLATFORM_PHP

RUN set -eux; \
    composer create-project "${SHOPWARE_PKG_NAME}:${SHOPWARE_PKG_VERSION}" /app --no-install; \
    composer config platform.php "${SHOPWARE_COMPOSER_PLATFORM_PHP}"; \
    composer config policy.advisories.block false

RUN set -eux; \
    composer install \
      --no-dev \
      --optimize-autoloader \
      --no-progress \
      --no-scripts \
      --ignore-platform-req=ext-gd \
      --ignore-platform-req=ext-intl \
      --ignore-platform-req=ext-pdo_mysql; \
    composer require symfony/redis-messenger:^7.4 league/flysystem-async-aws-s3:^3.0 \
      -W \
      --no-scripts \
      --no-progress \
      --update-no-dev \
      --ignore-platform-req=ext-gd \
      --ignore-platform-req=ext-intl \
      --ignore-platform-req=ext-pdo_mysql \
      --ignore-platform-req=ext-redis


FROM ${SHOPWARE_PHP_IMAGE}:${SHOPWARE_PHP_VERSION}
WORKDIR /var/www/html

USER root
RUN set -eux; \
    apk add --no-cache php83-gd         || apk add --no-cache php82-gd         || apk add --no-cache php-gd || true; \
    apk add --no-cache php83-intl       || apk add --no-cache php82-intl       || apk add --no-cache php-intl || true; \
    apk add --no-cache php83-pdo_mysql  || apk add --no-cache php82-pdo_mysql  || apk add --no-cache php-pdo_mysql || true; \
    apk add --no-cache php83-redis      || apk add --no-cache php82-redis      || apk add --no-cache php-redis || true

RUN set -eux; \
    d="$(php -r 'echo PHP_CONFIG_FILE_SCAN_DIR;')"; \
    { \
      echo 'session.save_handler = redis'; \
      echo 'session.save_path = ${REDIS_SESSION_TARGET}'; \
    } > "${d}/zz-session-redis.ini"

COPY --chown=www-data:www-data --from=builder /app /var/www/html

RUN mkdir -p /usr/src/shopware \
 && cp -a /var/www/html/. /usr/src/shopware/. \
 && chown -R www-data:www-data /var/www/html /usr/src/shopware

RUN set -eux; \
    mkdir -p \
      /var/www/html/files \
      /var/www/html/var \
      /var/www/html/public/media \
      /var/www/html/public/thumbnail \
      /var/www/html/public/sitemap \
      /var/www/html/public/theme; \
    chown -R www-data:www-data /var/www/html

USER www-data
