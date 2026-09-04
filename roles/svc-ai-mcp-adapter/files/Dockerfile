# Self-built MCP adapter image.
#
# Deliberately stdlib-only: the served surface is three JSON-RPC methods, and
# a dependency-free image has no transitive supply chain to audit per release.
ARG MCP_ADAPTER_BASE_IMAGE
ARG MCP_ADAPTER_BASE_VERSION
FROM ${MCP_ADAPTER_BASE_IMAGE}:${MCP_ADAPTER_BASE_VERSION}

WORKDIR /opt/adapter
COPY policy.py passthrough.py server.py sse.py /opt/adapter/

RUN adduser --system --no-create-home --disabled-login adapter
USER adapter

ENTRYPOINT ["python3", "/opt/adapter/server.py"]
