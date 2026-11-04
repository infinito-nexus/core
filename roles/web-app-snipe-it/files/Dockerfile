ARG SNIPE_IT_IMAGE
ARG SNIPE_IT_VERSION
FROM ${SNIPE_IT_IMAGE}:${SNIPE_IT_VERSION}

ARG SNIPE_IT_LOGIN_RBAC_CONTEXT

RUN sed -i 's#php artisan migrate --force#php artisan migrate --force --isolated#' /startup.sh

RUN printf 'SetEnvIf X-Forwarded-Preferred-Username "^(.+)$" INFINITO_SSO_USER=$1\nSetEnvIf X-Forwarded-Groups "^(.+)$" INFINITO_SSO_GROUPS=$1\nSetEnvIfExpr "-z env(\047INFINITO_SSO_PROXY_SECRET\047) || req(\047X-Infinito-Sso-Proxy\047) != env(\047INFINITO_SSO_PROXY_SECRET\047)" !INFINITO_SSO_USER !INFINITO_SSO_GROUPS\n' > /etc/apache2/conf.d/infinito-sso.conf

COPY --chown=apache:apache ${SNIPE_IT_LOGIN_RBAC_CONTEXT} /opt/infinito/snipe-it-login-rbac

USER apache
RUN composer config repositories.infinito-login-rbac '{"type": "path", "url": "/opt/infinito/snipe-it-login-rbac", "options": {"symlink": false}}' \
    && COMPOSER_CACHE_DIR=/dev/null composer require --no-interaction --no-scripts --no-audit infinito/snipe-it-login-rbac:1.0.0 \
    && php artisan package:discover --no-ansi | grep -F infinito/snipe-it-login-rbac
USER root
