ARG SNIPE_IT_IMAGE
ARG SNIPE_IT_VERSION
FROM ${SNIPE_IT_IMAGE}:${SNIPE_IT_VERSION}

RUN sed -i 's#php artisan migrate --force#php artisan migrate --force --isolated#' /startup.sh

RUN printf 'SetEnvIf X-Forwarded-Preferred-Username "^(.+)$" INFINITO_SSO_USER=$1\nSetEnvIfExpr "-z env(\047INFINITO_SSO_PROXY_SECRET\047) || req(\047X-Infinito-Sso-Proxy\047) != env(\047INFINITO_SSO_PROXY_SECRET\047)" !INFINITO_SSO_USER\n' > /etc/apache2/conf.d/infinito-sso.conf
