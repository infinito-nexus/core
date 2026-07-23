ARG FRIENDICA_IMAGE
ARG FRIENDICA_VERSION
FROM ${FRIENDICA_IMAGE}:${FRIENDICA_VERSION}

COPY friendica-init-gate.sh /usr/local/bin/friendica-init-gate.sh
RUN chmod 0755 /usr/local/bin/friendica-init-gate.sh
ENTRYPOINT ["/usr/local/bin/friendica-init-gate.sh"]
CMD ["apache2-foreground"]
