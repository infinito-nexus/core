ARG TOR_BASE_IMAGE
ARG TOR_BASE_VERSION
FROM ${TOR_BASE_IMAGE}:${TOR_BASE_VERSION}

ARG TOR_FLAVOR
ENV TOR_FLAVOR=${TOR_FLAVOR}

RUN rm -rf /var/lib/apt/lists/* \
 && apt-get -o Acquire::Retries=3 update \
 && apt-get -o Acquire::Retries=3 install -y --no-install-recommends tor \
 && if [ "${TOR_FLAVOR}" = "chutney" ]; then \
      apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
        git ca-certificates python3 python3-cryptography python3-networkx \
        python3-paramiko python3-rpyc python3-tomli-w python3-typeguard \
        python3-typing-extensions \
      && git clone --depth=1 https://gitlab.torproject.org/tpo/core/chutney /opt/chutney \
      && sed -i 's/^\( *\)self\.controlport_base: int = 8000$/\1self.controlport_base: int = 18000/' \
           /opt/chutney/lib/chutney/TorNet.py \
      && grep -q 'controlport_base: int = 18000' /opt/chutney/lib/chutney/TorNet.py ; \
    fi \
 && rm -rf /var/lib/apt/lists/*

ARG TOR_ENTRYPOINT_PATH
ARG TOR_HEALTHCHECK_PATH

COPY entrypoint.sh ${TOR_ENTRYPOINT_PATH}
COPY healthcheck.sh ${TOR_HEALTHCHECK_PATH}
RUN chmod 0755 ${TOR_ENTRYPOINT_PATH} ${TOR_HEALTHCHECK_PATH} \
 && ln -s ${TOR_ENTRYPOINT_PATH} /tor-entrypoint

ENTRYPOINT ["/tor-entrypoint"]
CMD ["-f", "/etc/tor/torrc"]
