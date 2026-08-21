ARG OPENPROJECT_IMAGE
ARG OPENPROJECT_VERSION
FROM ${OPENPROJECT_IMAGE}:${OPENPROJECT_VERSION}


COPY volumes/plugins/Gemfile.plugins /app/

RUN f=/app/app/models/queries/projects/filters/custom_field_filter.rb; g=/app/app/models/queries/projects/filters/custom_field_context.rb; \
    if [ -f "$f" ] && [ -f "$g" ] && ! grep -q "require_relative 'custom_field_context'" "$f"; then \
      sed -i "1irequire_relative 'custom_field_context'" "$f"; \
    fi


RUN bundle config unset deployment && bundle install && bundle config set deployment 'true'

RUN f=$(find /app/vendor/bundle -path '*grape*/lib/grape/exceptions/incompatible_option_values.rb' | head -1); \
    if [ -n "$f" ] && ! grep -q "require_relative 'base'" "$f"; then \
      sed -i "1irequire_relative 'base'" "$f"; \
    fi

RUN ./docker/prod/setup/precompile-assets.sh
