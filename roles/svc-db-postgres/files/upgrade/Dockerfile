ARG POSTGRES_IMAGE
ARG POSTGRES_VERSION
FROM ${POSTGRES_IMAGE}:${POSTGRES_VERSION}

ARG POSTGRES_OLD_MAJORS
ARG POSTGRES_TARGET_MAJOR
ARG POSTGRES_EXTENSION_PACKAGES

RUN set -eu; \
    sed -i "s/\$/ ${POSTGRES_OLD_MAJORS}/" /etc/apt/sources.list.d/pgdg.list; \
    packages=""; \
    for major in ${POSTGRES_OLD_MAJORS}; do \
      packages="${packages} postgresql-${major}"; \
      for extension in ${POSTGRES_EXTENSION_PACKAGES}; do packages="${packages} postgresql-${major}-${extension}"; done; \
    done; \
    for extension in ${POSTGRES_EXTENSION_PACKAGES}; do packages="${packages} postgresql-${POSTGRES_TARGET_MAJOR}-${extension}"; done; \
    rm -rf /var/lib/apt/lists/*; \
    apt-get -o Acquire::Retries=3 update; \
    apt-get -o Acquire::Retries=3 install -y --no-install-recommends ${packages}; \
    rm -rf /var/lib/apt/lists/*

COPY upgrade.sh /usr/local/bin/pg-upgrade-chain
RUN chmod 0755 /usr/local/bin/pg-upgrade-chain

ENTRYPOINT ["pg-upgrade-chain"]
