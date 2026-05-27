ARG SUITECRM_BASE_IMAGE
ARG SUITECRM_BASE_VERSION
FROM ${SUITECRM_BASE_IMAGE}:${SUITECRM_BASE_VERSION}

ARG SUITECRM_APP_VERSION
ARG SUITECRM_ENTRYPOINT_SCRIPT_HOST_REL
ARG SUITECRM_ENTRYPOINT_SCRIPT_DOCKER
ARG SUITECRM_LDAP_EXTENSION_DIR

# Install required system packages and PHP extensions
RUN rm -rf /var/lib/apt/lists/* \
  && apt-get update && apt-get install -y \
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

# Install Apache modules
RUN a2enmod rewrite headers

WORKDIR /var/www/html

# Adjust Apache DocumentRoot for SuiteCRM 8 (Symfony public/ dir)
RUN sed -ri 's!/var/www/html!/var/www/html/public!g' \
      /etc/apache2/sites-available/000-default.conf \
      /etc/apache2/apache2.conf

# Install Composer
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer

# Download SuiteCRM 8 source from GitHub
RUN set -eux; \
    SUITECRM_TAG="v${SUITECRM_APP_VERSION}"; \
    wget -qO /tmp/suitecrm.tar.gz \
      "https://github.com/SuiteCRM/SuiteCRM-Core/archive/refs/tags/${SUITECRM_TAG}.tar.gz"; \
    tar --strip-components=1 -xzf /tmp/suitecrm.tar.gz -C /var/www/html; \
    rm /tmp/suitecrm.tar.gz; \
    chmod +x bin/console

# Install PHP dependencies via Composer (critical!)
RUN set -eux; \
    composer install \
      --prefer-dist \
      --no-interaction \
      --optimize-autoloader \
      --no-scripts

# Legacy (SugarCRM) dependencies – Tinymce etc.
WORKDIR /var/www/html/public/legacy

RUN set -eux; \
    if [ -f composer.json ]; then \
      composer install --prefer-dist --no-interaction --optimize-autoloader --no-scripts; \
    fi

WORKDIR /var/www/html

# Install Node + Corepack
RUN rm -rf /var/lib/apt/lists/* \
 && apt-get update && apt-get install -y nodejs npm \
 && corepack enable && corepack prepare yarn@4.5.1 --activate \
 && rm -rf /var/lib/apt/lists/*

RUN yarn install --immutable \
 && yarn merge-angular-json \
 && yarn build

# Legacy theme SCSS -> CSS
RUN set -eux; \
    php ./vendor/bin/pscss -s compressed \
      public/legacy/themes/suite8/css/Dawn/style.scss \
      > public/legacy/themes/suite8/css/Dawn/style.css

# Copy entrypoint
COPY ${SUITECRM_ENTRYPOINT_SCRIPT_HOST_REL} ${SUITECRM_ENTRYPOINT_SCRIPT_DOCKER}
RUN chmod +x ${SUITECRM_ENTRYPOINT_SCRIPT_DOCKER} \
    && ln -sf "${SUITECRM_ENTRYPOINT_SCRIPT_DOCKER}" /entrypoint.sh

# Create LDAP Extension Directory
RUN mkdir -p "${SUITECRM_LDAP_EXTENSION_DIR}"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["apache2-foreground"]
