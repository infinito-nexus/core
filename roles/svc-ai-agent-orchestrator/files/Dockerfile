ARG AGENT_ORCHESTRATOR_BASE_IMAGE
ARG AGENT_ORCHESTRATOR_BASE_VERSION
FROM ${AGENT_ORCHESTRATOR_BASE_IMAGE}:${AGENT_ORCHESTRATOR_BASE_VERSION}

WORKDIR /opt/orchestrator
COPY requirements.txt /opt/orchestrator/requirements.txt
RUN pip install --no-cache-dir -r /opt/orchestrator/requirements.txt

COPY server.py /opt/orchestrator/
COPY utils /opt/orchestrator/utils
COPY agents /opt/orchestrator/agents
COPY roles /opt/orchestrator/roles

RUN adduser --system --no-create-home --disabled-login orchestrator
USER orchestrator

ENTRYPOINT ["python3", "/opt/orchestrator/server.py"]
