ARG MACHINE_BASE_IMAGE
FROM ${MACHINE_BASE_IMAGE}

COPY init.sh /tmp/docs-guide-init.sh
RUN /bin/sh /tmp/docs-guide-init.sh && rm -f /tmp/docs-guide-init.sh

ENTRYPOINT ["/sbin/init"]
