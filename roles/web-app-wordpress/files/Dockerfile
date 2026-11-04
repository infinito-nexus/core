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

ARG WORDPRESS_S3_UPLOADS_ARCHIVE
ARG WORDPRESS_S3_UPLOADS_SRC
RUN if [ -n "${WORDPRESS_S3_UPLOADS_ARCHIVE}" ]; then \
      curl -fsSL --connect-timeout 5 --max-time 300 -o /tmp/s3-uploads.zip \
        "${WORDPRESS_S3_UPLOADS_ARCHIVE}" && \
      mkdir -p "${WORDPRESS_S3_UPLOADS_SRC}" && \
      unzip -q /tmp/s3-uploads.zip -d "${WORDPRESS_S3_UPLOADS_SRC}" && \
      rm /tmp/s3-uploads.zip; \
    fi

ARG WORDPRESS_CONFIG_UPLD_REL
COPY ${WORDPRESS_CONFIG_UPLD_REL} $PHP_INI_DIR/conf.d/
