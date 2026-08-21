ARG SNIPE_IT_IMAGE
ARG SNIPE_IT_VERSION
FROM ${SNIPE_IT_IMAGE}:${SNIPE_IT_VERSION}

RUN sed -i 's#php artisan migrate --force#php artisan migrate --force --isolated#' /startup.sh
