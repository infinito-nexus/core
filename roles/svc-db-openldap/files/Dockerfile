ARG OPENLDAP_IMAGE
ARG OPENLDAP_VERSION
FROM ${OPENLDAP_IMAGE}:${OPENLDAP_VERSION}

ENV DEBIAN_FRONTEND=noninteractive

RUN rm -rf /var/lib/apt/lists/* \
 && apt-get -o Acquire::Retries=3 update \
 && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    slapd slapd-contrib ldap-utils ca-certificates tini \
 && rm -rf /var/lib/apt/lists/* \
 && rm -rf /etc/ldap/slapd.d/* /var/lib/ldap/* \
 && mkdir -p /run/slapd /var/lib/ldap /etc/ldap/slapd.d \
 && chown -R openldap:openldap /run/slapd /var/lib/ldap /etc/ldap/slapd.d

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

COPY healthcheck.sh /healthcheck.sh
RUN chmod +x /healthcheck.sh

EXPOSE 389

HEALTHCHECK --interval=2m --timeout=5s --start-period=10m --retries=12 --start-interval=5s \
  CMD ["/healthcheck.sh"]

ENTRYPOINT ["/usr/bin/tini","--","/entrypoint.sh"]
