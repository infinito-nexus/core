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
      && git clone --depth=1 https://gitlab.torproject.org/tpo/core/chutney /opt/chutney ; \
    fi \
 && rm -rf /var/lib/apt/lists/*

ARG TOR_ENTRYPOINT_PATH
ARG TOR_HEALTHCHECK_PATH
ARG TOR_CHUTNEY_SCRIPT_PATH
ENV TOR_CHUTNEY_SCRIPT_PATH=${TOR_CHUTNEY_SCRIPT_PATH}

COPY entrypoint.sh ${TOR_ENTRYPOINT_PATH}
COPY healthcheck.sh ${TOR_HEALTHCHECK_PATH}
COPY chutney.sh ${TOR_CHUTNEY_SCRIPT_PATH}
RUN chmod 0755 ${TOR_ENTRYPOINT_PATH} ${TOR_HEALTHCHECK_PATH} ${TOR_CHUTNEY_SCRIPT_PATH} \
 && ln -s ${TOR_ENTRYPOINT_PATH} /tor-entrypoint

ARG TOR_CHUTNEY_NET
ARG TOR_CHUTNEY_ADDRESS
ARG TOR_CHUTNEY_PORT_BASES
ARG TOR_CHUTNEY_PORT_SPAN
ENV TOR_CHUTNEY_ADDRESS=${TOR_CHUTNEY_ADDRESS}

RUN if [ "${TOR_FLAVOR}" = "chutney" ]; then \
      "${TOR_CHUTNEY_SCRIPT_PATH}" build /opt/chutney "${TOR_CHUTNEY_NET}" \
        "${TOR_CHUTNEY_ADDRESS}" "${TOR_CHUTNEY_PORT_BASES}" "${TOR_CHUTNEY_PORT_SPAN}" ; \
    fi

ENTRYPOINT ["/tor-entrypoint"]
CMD ["-f", "/etc/tor/torrc"]
