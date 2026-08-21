# Multi-stage Hugo build:
#   Stage 1 (builder) runs Hugo against the cloned upstream content.
#   Stage 2 (serve)   ships the rendered /public/ via nginx.
# Both base-image refs are pinned via build args sourced from
# meta/services.yml and surface in the global image-drift report.

ARG HUGO_BUILDER_IMAGE
ARG HUGO_BUILDER_VERSION
ARG HUGO_NGINX_IMAGE
ARG HUGO_NGINX_VERSION

FROM ${HUGO_BUILDER_IMAGE}:${HUGO_BUILDER_VERSION} AS builder

ARG HUGO_BASE_URL
ARG HUGO_ENVIRONMENT
ARG HUGO_MINIFY

WORKDIR /src
COPY ./services/repository/ /src/

RUN apk add --no-cache nodejs npm
RUN set -eu; \
    if [ -f package.json ]; then \
        npm install --no-audit --no-fund --no-progress; \
    fi

RUN set -eu; \
    if [ "${HUGO_MINIFY}" = "true" ]; then \
        hugo --minify -e "${HUGO_ENVIRONMENT}" -b "${HUGO_BASE_URL}" -d /public; \
    else \
        hugo -e "${HUGO_ENVIRONMENT}" -b "${HUGO_BASE_URL}" -d /public; \
    fi

FROM ${HUGO_NGINX_IMAGE}:${HUGO_NGINX_VERSION}

COPY --from=builder /public/ /usr/share/nginx/html/

EXPOSE 80
