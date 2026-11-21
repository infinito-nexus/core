ARG INFINITO_PARENT_IMAGE
FROM ${INFINITO_PARENT_IMAGE}

COPY init.sh /tmp/target-init.sh
RUN /bin/sh /tmp/target-init.sh && rm -f /tmp/target-init.sh

ENV container=docker
STOPSIGNAL SIGRTMIN+3

ENTRYPOINT ["/sbin/init"]
