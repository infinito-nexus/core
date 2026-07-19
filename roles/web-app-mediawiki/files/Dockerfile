ARG MEDIAWIKI_IMAGE
ARG MEDIAWIKI_VERSION
FROM ${MEDIAWIKI_IMAGE}:${MEDIAWIKI_VERSION}

SHELL ["/bin/bash", "-lc"]

RUN set -euo pipefail \
 && export DEBIAN_FRONTEND=noninteractive \
 && rm -rf /var/lib/apt/lists/* \
 && apt-get update -y \
 && apt-get install -y --no-install-recommends ca-certificates curl git unzip \
 && update-ca-certificates \
 && curl --connect-timeout 5 --max-time 120 -fsSL https://getcomposer.org/installer -o /tmp/composer-setup.php \
 && php /tmp/composer-setup.php --install-dir=/usr/local/bin --filename=composer \
 && composer --version \
 && rm -f /tmp/composer-setup.php \
 && rm -rf /var/lib/apt/lists/*
