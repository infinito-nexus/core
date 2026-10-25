ARG AGENT_ORCHESTRATOR_BASE_IMAGE
ARG AGENT_ORCHESTRATOR_BASE_VERSION
FROM ${AGENT_ORCHESTRATOR_BASE_IMAGE}:${AGENT_ORCHESTRATOR_BASE_VERSION}

WORKDIR /opt/orchestrator
COPY server.py /opt/orchestrator/
COPY utils /opt/orchestrator/utils

RUN adduser --system --no-create-home --disabled-login orchestrator
USER orchestrator

ENTRYPOINT ["python3", "/opt/orchestrator/server.py"]
