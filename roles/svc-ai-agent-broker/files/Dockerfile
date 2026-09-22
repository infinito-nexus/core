ARG AGENT_BROKER_BASE_IMAGE
ARG AGENT_BROKER_BASE_VERSION
FROM ${AGENT_BROKER_BASE_IMAGE}:${AGENT_BROKER_BASE_VERSION}

WORKDIR /opt/broker
COPY access.py agents.py engine.py server.py /opt/broker/

RUN adduser --system --no-create-home --disabled-login broker
USER broker

ENTRYPOINT ["python3", "/opt/broker/server.py"]
