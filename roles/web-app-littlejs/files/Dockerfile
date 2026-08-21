ARG LITTLEJS_IMAGE
ARG LITTLEJS_VERSION
FROM ${LITTLEJS_IMAGE}:${LITTLEJS_VERSION}

ARG LITTLEJS_APP_REL
ARG LITTLEJS_INDEX_HOST_REL
ARG LITTLEJS_RUN_HOST_REL

COPY ./${LITTLEJS_APP_REL}/examples /usr/share/nginx/html/examples
COPY ./${LITTLEJS_APP_REL}/dist     /usr/share/nginx/html/dist

COPY ./${LITTLEJS_INDEX_HOST_REL} /usr/share/nginx/html/index.html

COPY ./${LITTLEJS_RUN_HOST_REL} /usr/share/nginx/html/examples/shorts/run.html
