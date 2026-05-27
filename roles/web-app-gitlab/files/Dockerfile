ARG GITLAB_IMAGE
ARG GITLAB_VERSION
FROM ${GITLAB_IMAGE}:${GITLAB_VERSION}

RUN sed -i '1i require_relative "../redis"' \
    /opt/gitlab/embedded/service/gitlab-rails/lib/gitlab/instrumentation/redis.rb
