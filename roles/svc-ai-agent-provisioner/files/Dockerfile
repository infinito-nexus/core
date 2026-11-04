ARG AGENT_PROVISIONER_BASE_IMAGE
ARG AGENT_PROVISIONER_BASE_VERSION
FROM ${AGENT_PROVISIONER_BASE_IMAGE}:${AGENT_PROVISIONER_BASE_VERSION}

WORKDIR /opt/provisioner
COPY server.py /opt/provisioner/
COPY utils /opt/provisioner/utils

RUN adduser --system --no-create-home --disabled-login provisioner
USER provisioner

ENTRYPOINT ["python3", "/opt/provisioner/server.py"]
