ARG DECIDIM_IMAGE
ARG DECIDIM_VERSION
FROM ${DECIDIM_IMAGE}:${DECIDIM_VERSION}

ARG DECIDIM_PATCH_SCRIPT_HOST_REL
ARG DECIDIM_PATCH_SCRIPT_DOCKER
ARG DECIDIM_PATCH_RUBY_HOST_REL
ARG DECIDIM_PATCH_RUBY_DOCKER

# Add omniauth_openid_connect + aws-sdk-s3 to Gemfile and install
RUN echo "gem 'omniauth_openid_connect'" >> /code/Gemfile && \
    echo "gem 'aws-sdk-s3', require: false" >> /code/Gemfile && \
    cd /code && bundle install --quiet

# Copy patch script + ruby snippets it sources, then run
COPY ${DECIDIM_PATCH_SCRIPT_HOST_REL} ${DECIDIM_PATCH_SCRIPT_DOCKER}
COPY ${DECIDIM_PATCH_RUBY_HOST_REL}/ ${DECIDIM_PATCH_RUBY_DOCKER}/
RUN python3 ${DECIDIM_PATCH_SCRIPT_DOCKER}
