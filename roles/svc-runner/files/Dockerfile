ARG RUNNER_BASE_IMAGE
FROM ${RUNNER_BASE_IMAGE}

ARG RUNNER_UID
ARG RUNNER_GID

# Runner binary runtime deps + Docker CLI + Python 3 for CI scripts
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
        gettext-base \
        make \
        python3 \
        python3-pip \
        python3-venv \
        sudo \
        tar \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | gpg --dearmor -o /usr/share/keyrings/docker.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker.gpg] \
        https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
        > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf python3 /usr/bin/python

RUN groupadd -g "${RUNNER_GID}" github-runner \
    && useradd -u "${RUNNER_UID}" -g "${RUNNER_GID}" -m -s /bin/bash github-runner \
    && echo "github-runner ALL=(ALL) NOPASSWD: ALL" > /etc/sudoers.d/github-runner \
    && chmod 0440 /etc/sudoers.d/github-runner

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

WORKDIR /runner
USER github-runner
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
