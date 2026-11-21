ARG MATOMO_IMAGE
ARG MATOMO_VERSION
FROM ${MATOMO_IMAGE}:${MATOMO_VERSION}

ARG MATOMO_OIDC_PLUGIN_SOURCE
ARG MATOMO_OIDC_PLUGIN_ARCHIVE

RUN install -d -o www-data -g www-data /var/www/html/tmp

RUN set -eux; \
	curl -fsSL --connect-timeout 5 --max-time 300 -o /tmp/oidc-plugin.tar.gz "${MATOMO_OIDC_PLUGIN_ARCHIVE}"; \
	install -d "${MATOMO_OIDC_PLUGIN_SOURCE}"; \
	tar --strip-components=1 -xzf /tmp/oidc-plugin.tar.gz -C "${MATOMO_OIDC_PLUGIN_SOURCE}"; \
	rm /tmp/oidc-plugin.tar.gz; \
	test -f "${MATOMO_OIDC_PLUGIN_SOURCE}/plugin.json"
