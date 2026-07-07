ARG ESPOCRM_IMAGE
ARG ESPOCRM_VERSION
FROM ${ESPOCRM_IMAGE}:${ESPOCRM_VERSION}

ARG ESPOCRM_SCRIPT_SEED_HOST_REL
ARG ESPOCRM_SCRIPT_SEED_DOCKER
ARG ESPOCRM_ENTRYPOINT_SCRIPT_HOST_REL
ARG ESPOCRM_ENTRYPOINT_SCRIPT_DOCKER

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
