ARG YOURLS_IMAGE
ARG YOURLS_VERSION
FROM ${YOURLS_IMAGE}:${YOURLS_VERSION}

COPY infinito_sso.php /var/www/html/user/cache.php
RUN chown www-data:www-data /var/www/html/user/cache.php
