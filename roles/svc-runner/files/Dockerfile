FROM ubuntu:22.04

ARG RUNNER_UID=900
ARG RUNNER_GID=900

# Runner binary runtime deps + Docker CLI for CI jobs + sudo for cleanup ops
RUN rm -rf /var/lib/apt/lists/* \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
        libicu-dev \
        libssl-dev \
        sudo \
        tar \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /usr/share/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g "${RUNNER_GID}" github-runner \
    && useradd -u "${RUNNER_UID}" -g "${RUNNER_GID}" -m -s /bin/bash github-runner

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /runner
USER github-runner
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
