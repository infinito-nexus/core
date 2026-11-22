ARG XWIKI_IMAGE
ARG XWIKI_VERSION
FROM ${XWIKI_IMAGE}:${XWIKI_VERSION}
COPY java-with-ca-trust.sh /usr/local/bin/java-with-ca-trust.sh
COPY xwiki-entrypoint.sh /usr/local/bin/infinito-xwiki-entrypoint.sh
RUN chmod 0755 /usr/local/bin/java-with-ca-trust.sh /usr/local/bin/infinito-xwiki-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/java-with-ca-trust.sh", "/usr/local/bin/infinito-xwiki-entrypoint.sh"]
CMD ["xwiki"]
