ARG OPENRESTY_IMAGE
ARG OPENRESTY_VERSION
FROM ${OPENRESTY_IMAGE}:${OPENRESTY_VERSION}

ARG PROMETHEUS_ENABLED
ARG LUA_PROMETHEUS_URL_MAIN
ARG LUA_PROMETHEUS_URL_COUNTER
ARG LUA_PROMETHEUS_URL_KEYS

RUN case "${PROMETHEUS_ENABLED}" in \
      true|True|TRUE|1|yes) \
        apk add --no-cache wget \
        && mkdir -p /usr/local/openresty/lualib/resty \
        && wget -nv --tries=5 --waitretry=15 --retry-on-http-error=429,500,502,503,504 -O /usr/local/openresty/lualib/resty/prometheus.lua "$LUA_PROMETHEUS_URL_MAIN" \
        && wget -nv --tries=5 --waitretry=15 --retry-on-http-error=429,500,502,503,504 -O /usr/local/openresty/lualib/prometheus_resty_counter.lua "$LUA_PROMETHEUS_URL_COUNTER" \
        && wget -nv --tries=5 --waitretry=15 --retry-on-http-error=429,500,502,503,504 -O /usr/local/openresty/lualib/prometheus_keys.lua "$LUA_PROMETHEUS_URL_KEYS" \
        ;; \
    esac
