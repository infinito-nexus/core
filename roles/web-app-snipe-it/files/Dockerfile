ARG SNIPE_IT_IMAGE
ARG SNIPE_IT_VERSION
FROM ${SNIPE_IT_IMAGE}:${SNIPE_IT_VERSION}

# --isolated takes a redis lock so concurrent replicas don't race the first migration
RUN sed -i 's#php artisan migrate --force#php artisan migrate --force --isolated#' /startup.sh
