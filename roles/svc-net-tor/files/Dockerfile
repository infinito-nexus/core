ARG TOR_BASE_IMAGE
ARG TOR_BASE_VERSION
FROM ${TOR_BASE_IMAGE}:${TOR_BASE_VERSION}

RUN rm -rf /var/lib/apt/lists/* \
 && apt-get -o Acquire::Retries=3 update \
 && apt-get -o Acquire::Retries=3 install -y --no-install-recommends tor \
 && rm -rf /var/lib/apt/lists/*

ENTRYPOINT ["tor"]
CMD ["-f", "/etc/tor/torrc"]
