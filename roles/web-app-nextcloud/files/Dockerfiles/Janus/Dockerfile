ARG JANUS_BASE_IMAGE
ARG JANUS_BASE_VERSION
FROM ${JANUS_BASE_IMAGE}:${JANUS_BASE_VERSION} AS build
ARG JANUS_REPOSITORY
ARG JANUS_REF

WORKDIR /src
RUN set -ex; \
    apk upgrade --no-cache -a; \
    apk add --no-cache \
        ca-certificates \
        git \
        autoconf \
        automake \
        build-base \
        pkgconfig \
        libtool \
        util-linux \
        glib-dev \
        zlib-dev \
        openssl-dev \
        jansson-dev \
        libnice-dev \
        libconfig-dev \
        libsrtp-dev \
        libusrsctp-dev \
        gengetopt-dev \
        libwebsockets-dev; \
    git clone --recursive "${JANUS_REPOSITORY}" --depth=1 --single-branch --branch "${JANUS_REF}" /src; \
    /src/autogen.sh; \
    /src/configure --disable-rabbitmq --disable-mqtt --disable-boringssl; \
    make; \
    make install; \
    make configs; \
    rename -v ".jcfg.sample" ".jcfg" /usr/local/etc/janus/*.jcfg.sample

FROM ${JANUS_BASE_IMAGE}:${JANUS_BASE_VERSION}

COPY --from=build /usr/local /usr/local

RUN set -ex; \
    apk upgrade --no-cache -a; \
    apk add --no-cache \
        ca-certificates \
        tzdata \
        netcat-openbsd \
        glib \
        zlib \
        libssl3 \
        libcrypto3 \
        jansson \
        libnice \
        libconfig \
        libsrtp \
        libusrsctp \
        libwebsockets; \
    mkdir -p /usr/local/lib/janus/loggers; \
    adduser -D -H -u 1000 janus

USER janus
ENTRYPOINT ["janus", "--disable-colors", "--log-stdout", "--full-trickle", "--debug-level", "3"]
