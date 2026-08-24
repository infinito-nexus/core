ARG CONFLUENCE_IMAGE
ARG CONFLUENCE_VERSION
FROM ${CONFLUENCE_IMAGE}:${CONFLUENCE_VERSION}

ARG CONFLUENCE_HOME


RUN mkdir -p ${CONFLUENCE_HOME} && \
    chown -R 2001:2001 ${CONFLUENCE_HOME}
RUN printf "confluence.home=${CONFLUENCE_HOME}\n" \
  > /opt/atlassian/confluence/confluence/WEB-INF/classes/confluence-init.properties
