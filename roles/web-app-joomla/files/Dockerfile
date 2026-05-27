ARG JOOMLA_IMAGE
ARG JOOMLA_VERSION
FROM ${JOOMLA_IMAGE}:${JOOMLA_VERSION}

# Composer + tooling for the runtime build of the plg_system_keycloak
# OIDC plugin (requirement 013). The plugin's PHP dependencies
# (jumbojett/openid-connect-php) are vendored at deploy time inside
# the running container via `composer install`, so the host never
# needs PHP/Composer. `unzip` is required by Joomla's
# `extension:install --path=<zip>` CLI.
RUN rm -rf /var/lib/apt/lists/* \
    && apt-get update \
    && apt-get install -y --no-install-recommends git unzip curl ca-certificates \
    && curl -sS https://getcomposer.org/installer | php -- --install-dir=/usr/local/bin --filename=composer \
    && rm -rf /var/lib/apt/lists/*
