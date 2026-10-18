ARG MATTERMOST_BASE_IMAGE
ARG MATTERMOST_BASE_VERSION

FROM ${MATTERMOST_BASE_IMAGE}:${MATTERMOST_BASE_VERSION}

ARG MATTERMOST_VERSION

RUN rm -rf /var/lib/apt/lists/* \
  && apt-get -o Acquire::Retries=3 update \
  && apt-get -o Acquire::Retries=3 install -y --no-install-recommends \
    ca-certificates \
    curl \
    mailcap \
    media-types \
    poppler-utils \
    tidy \
    tzdata \
    unrtf \
    wv \
  && rm -rf /var/lib/apt/lists/*

COPY install.sh /tmp/install.sh
RUN bash /tmp/install.sh "${MATTERMOST_VERSION}" && rm /tmp/install.sh

ENV PATH="/mattermost/bin:${PATH}" \
  MM_SERVICESETTINGS_ENABLELOCALMODE="true" \
  MM_INSTALL_TYPE="docker"

USER mattermost
WORKDIR /mattermost
EXPOSE 8065 8067 8074
CMD ["/mattermost/bin/mattermost"]
