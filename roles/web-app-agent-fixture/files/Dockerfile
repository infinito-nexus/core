ARG FIXTURE_IMAGE
ARG FIXTURE_VERSION
FROM ${FIXTURE_IMAGE}:${FIXTURE_VERSION}

COPY app/html/ /usr/share/nginx/html/
COPY app/config/nginx.conf /etc/nginx/conf.d/default.conf
