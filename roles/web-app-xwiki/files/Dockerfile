ARG XWIKI_IMAGE
ARG XWIKI_VERSION
FROM ${XWIKI_IMAGE}:${XWIKI_VERSION}
ARG XWIKI_SUPERADMIN_PASSWORD
RUN printf '%s\n' \
  'xwiki.superadmin=1' \
  "xwiki.superadminpassword=${XWIKI_SUPERADMIN_PASSWORD}" \
  >> /usr/local/tomcat/webapps/ROOT/WEB-INF/xwiki.cfg
COPY xwiki-entrypoint.sh /usr/local/bin/infinito-xwiki-entrypoint.sh
RUN chmod 0755 /usr/local/bin/infinito-xwiki-entrypoint.sh
ENTRYPOINT ["/usr/local/bin/infinito-xwiki-entrypoint.sh"]
CMD ["xwiki"]
