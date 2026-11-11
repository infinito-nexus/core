ARG WORDPRESS_IMAGE
ARG WORDPRESS_VERSION
FROM ${WORDPRESS_IMAGE}:${WORDPRESS_VERSION}

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get -o Acquire::Retries=3 update && \
    apt-get -o Acquire::Retries=3 install -y ca-certificates msmtp msmtp-mta unzip && \
    rm -rf /var/lib/apt/lists/*

RUN curl --connect-timeout 5 --max-time 300 -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && \
    chmod +x wp-cli.phar && \
    mv wp-cli.phar /usr/local/bin/wp

COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

ARG WORDPRESS_S3_UPLOADS_VERSION
ARG WORDPRESS_S3_UPLOADS_SRC
RUN if [ -n "${WORDPRESS_S3_UPLOADS_VERSION}" ]; then \
      COMPOSER_ALLOW_SUPERUSER=1 composer create-project --no-dev --no-interaction \
        --no-progress --prefer-dist humanmade/s3-uploads \
        "${WORDPRESS_S3_UPLOADS_SRC}" "${WORDPRESS_S3_UPLOADS_VERSION}"; \
    fi

ARG WORDPRESS_CONFIG_UPLD_REL
COPY ${WORDPRESS_CONFIG_UPLD_REL} $PHP_INI_DIR/conf.d/
