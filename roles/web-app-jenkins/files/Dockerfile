ARG JENKINS_IMAGE
ARG JENKINS_VERSION
FROM ${JENKINS_IMAGE}:${JENKINS_VERSION}

USER root
RUN rm -rf /var/lib/apt/lists/* \
    && apt-get -o Acquire::Retries=3 update \
    && apt-get -o Acquire::Retries=3 install -y --no-install-recommends ca-certificates curl gnupg \
    && rm -rf /var/lib/apt/lists/*

# The OIC plugin uses the JVM's own HTTPS stack to fetch Keycloak's
# `.well-known/openid-configuration`. Without the project CA in the
# JVM cacerts the discovery call fails with `Well known configuration
# could not be loaded, login can not proceed.` and the OIDC redirect
# never fires. Make cacerts writable so a runtime entrypoint (running
# as the jenkins user) can `keytool -importcert` the CA that the
# project's `with-ca-trust` wrapper drops at $CA_TRUST_CERT_HOST.
RUN chmod 0666 /opt/java/openjdk/lib/security/cacerts
COPY java-with-ca-trust.sh /usr/local/bin/java-with-ca-trust.sh
RUN chmod +x /usr/local/bin/java-with-ca-trust.sh

USER jenkins

# Pre-install plugins via the official jenkins-plugin-cli, baked into
# the image so first start-up does not block on plugin download.
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

ENTRYPOINT ["/usr/local/bin/java-with-ca-trust.sh"]
CMD ["/usr/local/bin/jenkins.sh"]
