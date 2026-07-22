ARG JENKINS_IMAGE
ARG JENKINS_VERSION
FROM ${JENKINS_IMAGE}:${JENKINS_VERSION}

USER root
RUN rm -rf /var/lib/apt/lists/* \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates curl gnupg \
    && rm -rf /var/lib/apt/lists/*

RUN chmod 0666 /opt/java/openjdk/lib/security/cacerts
COPY java-with-ca-trust.sh /usr/local/bin/java-with-ca-trust.sh
RUN chmod +x /usr/local/bin/java-with-ca-trust.sh

USER jenkins

COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

ENTRYPOINT ["/usr/local/bin/java-with-ca-trust.sh"]
CMD ["/usr/local/bin/jenkins.sh"]
