ARG LAM_IMAGE
ARG LAM_VERSION
FROM ${LAM_IMAGE}:${LAM_VERSION}

USER root

RUN set -eu; \
    php_version="$(php -r 'echo PHP_MAJOR_VERSION . "." . PHP_MINOR_VERSION;')"; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get -o Acquire::Retries=3 update; \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends "php${php_version}-redis"; \
    rm -rf /var/lib/apt/lists/*; \
    php -m | grep -qx redis

RUN set -eu; \
    php_version="$(php -r 'echo PHP_MAJOR_VERSION . "." . PHP_MINOR_VERSION;')"; \
    for sapi in apache2 cli; do \
      conf_dir="/etc/php/${php_version}/${sapi}/conf.d"; \
      test -d "${conf_dir}"; \
      printf '%s\n' \
        'session.save_handler = redis' \
        'session.save_path = "${LAM_SESSION_SAVE_PATH}"' \
        'redis.session.locking_enabled = 1' \
        'redis.session.lock_retries = -1' \
        > "${conf_dir}/99-infinito-session.ini"; \
    done

COPY login_search.php /usr/local/share/infinito-lam/login_search.php
COPY entrypoint.sh /usr/local/bin/infinito-lam-entrypoint.sh
RUN chmod 0755 /usr/local/bin/infinito-lam-entrypoint.sh
CMD ["/usr/local/bin/infinito-lam-entrypoint.sh"]
