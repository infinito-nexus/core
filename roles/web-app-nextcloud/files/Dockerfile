ARG NEXTCLOUD_IMAGE
ARG NEXTCLOUD_VERSION
FROM ${NEXTCLOUD_IMAGE}:${NEXTCLOUD_VERSION}
ARG NEXTCLOUD_ONLYOFFICE_ENABLED
ARG NEXTCLOUD_INIT_GATE_FILE

RUN case "${NEXTCLOUD_ONLYOFFICE_ENABLED}" in \
      true) apk add --no-cache ca-certificates && update-ca-certificates ;; \
      false) ;; \
      *) echo "NEXTCLOUD_ONLYOFFICE_ENABLED must be true or false, got '${NEXTCLOUD_ONLYOFFICE_ENABLED}'" >&2; exit 1 ;; \
    esac

COPY ${NEXTCLOUD_INIT_GATE_FILE} /usr/local/bin/init-gate.sh
RUN chmod 0755 /usr/local/bin/init-gate.sh
ENTRYPOINT ["/usr/local/bin/init-gate.sh"]
CMD ["php-fpm"]
