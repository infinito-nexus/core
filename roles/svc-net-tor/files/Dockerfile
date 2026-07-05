ARG TOR_BASE_IMAGE
ARG TOR_BASE_VERSION
FROM ${TOR_BASE_IMAGE}:${TOR_BASE_VERSION}

# Install the distro-packaged Tor daemon (signed Debian package = verifiable
# provenance for a security-critical anonymity service). No :latest anywhere.
RUN rm -rf /var/lib/apt/lists/* \
 && apt-get update \
 && apt-get install -y --no-install-recommends tor \
 && rm -rf /var/lib/apt/lists/*

# Run in the foreground as PID 1; config + hidden-service keys are bind-mounted.
ENTRYPOINT ["tor"]
CMD ["-f", "/etc/tor/torrc"]
