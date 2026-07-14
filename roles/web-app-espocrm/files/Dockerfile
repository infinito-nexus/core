ARG ESPOCRM_IMAGE
ARG ESPOCRM_VERSION
FROM ${ESPOCRM_IMAGE}:${ESPOCRM_VERSION}

ARG ESPOCRM_SCRIPT_SEED_HOST_REL
ARG ESPOCRM_SCRIPT_SEED_DOCKER
ARG ESPOCRM_ENTRYPOINT_SCRIPT_HOST_REL
ARG ESPOCRM_ENTRYPOINT_SCRIPT_DOCKER

RUN cp -a /usr/src/espocrm/. /var/www/html/

# Exception: upstream v10 entrypoint hardcodes `set-password admin`, killing installs with a non-default admin name; the grep guard fails the build if the line changes.
RUN sed -i 's|bin/command set-password admin |bin/command set-password "$ESPOCRM_ADMIN_USERNAME" |' /usr/local/bin/docker-entrypoint.sh \
    && grep -qF 'set-password "$ESPOCRM_ADMIN_USERNAME"' /usr/local/bin/docker-entrypoint.sh

RUN sed -i 's#bin/command create-admin-user "$ESPOCRM_ADMIN_USERNAME" >/dev/null 2>&1#bin/command create-admin-user "$ESPOCRM_ADMIN_USERNAME" >/dev/null 2>\&1 || true#' /usr/local/bin/docker-entrypoint.sh \
    && grep -qF 'create-admin-user "$ESPOCRM_ADMIN_USERNAME" >/dev/null 2>&1 || true' /usr/local/bin/docker-entrypoint.sh

COPY ${ESPOCRM_SCRIPT_SEED_HOST_REL} ${ESPOCRM_SCRIPT_SEED_DOCKER}
RUN chmod +x ${ESPOCRM_SCRIPT_SEED_DOCKER}

COPY ${ESPOCRM_ENTRYPOINT_SCRIPT_HOST_REL} ${ESPOCRM_ENTRYPOINT_SCRIPT_DOCKER}
RUN chmod +x ${ESPOCRM_ENTRYPOINT_SCRIPT_DOCKER} \
    && ln -sf "${ESPOCRM_ENTRYPOINT_SCRIPT_DOCKER}" /entrypoint.sh

RUN { \
      echo 'session.save_handler = files'; \
      echo 'session.save_path = "/var/www/html/data/.sessions"'; \
      echo 'session.gc_probability = 1'; \
      echo 'session.gc_divisor = 100'; \
      echo 'session.gc_maxlifetime = 1440'; \
    } > "${PHP_INI_DIR}/conf.d/zz-espocrm-session.ini"

ENTRYPOINT ["/entrypoint.sh"]
