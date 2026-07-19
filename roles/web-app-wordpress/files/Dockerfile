ARG WORDPRESS_IMAGE
ARG WORDPRESS_VERSION
FROM ${WORDPRESS_IMAGE}:${WORDPRESS_VERSION}

RUN rm -rf /var/lib/apt/lists/* && \
    apt-get update && \
    apt-get install -y ca-certificates msmtp msmtp-mta && \
    rm -rf /var/lib/apt/lists/*

RUN curl --connect-timeout 5 --max-time 300 -O https://raw.githubusercontent.com/wp-cli/builds/gh-pages/phar/wp-cli.phar && \
    chmod +x wp-cli.phar && \
    mv wp-cli.phar /usr/local/bin/wp

ARG WORDPRESS_CONFIG_UPLD_REL
COPY ${WORDPRESS_CONFIG_UPLD_REL} $PHP_INI_DIR/conf.d/
