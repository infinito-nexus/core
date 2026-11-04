ARG PHPMYADMIN_IMAGE
ARG PHPMYADMIN_VERSION
FROM ${PHPMYADMIN_IMAGE}:${PHPMYADMIN_VERSION}

ARG PHPMYADMIN_PHPREDIS_VERSION

RUN set -eu; \
    : "${PHPMYADMIN_PHPREDIS_VERSION:?}"; \
    pecl install "redis-${PHPMYADMIN_PHPREDIS_VERSION}"; \
    docker-php-ext-enable redis; \
    rm -rf /tmp/pear; \
    php -m | grep -qx redis

RUN set -eu; \
    printf '%s\n' \
      'session.save_handler = redis' \
      'session.save_path = "${PHPMYADMIN_SESSION_SAVE_PATH}"' \
      'redis.session.locking_enabled = 1' \
      'redis.session.lock_retries = -1' \
      > "${PHP_INI_DIR}/conf.d/zz-infinito-session.ini"; \
    test "$(PHPMYADMIN_SESSION_SAVE_PATH=tcp://probe:6379 php -r 'echo ini_get("session.save_handler"), " ", ini_get("session.save_path");')" = "redis tcp://probe:6379"
