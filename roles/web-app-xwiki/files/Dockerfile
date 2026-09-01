ARG XWIKI_IMAGE
ARG XWIKI_VERSION
FROM ${XWIKI_IMAGE}:${XWIKI_VERSION}
COPY xwiki-entrypoint.sh /usr/local/bin/infinito-xwiki-entrypoint.sh
RUN chmod 0755 /usr/local/bin/infinito-xwiki-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/infinito-xwiki-entrypoint.sh"]
CMD ["xwiki"]
