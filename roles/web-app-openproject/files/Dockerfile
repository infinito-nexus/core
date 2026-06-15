ARG OPENPROJECT_IMAGE
ARG OPENPROJECT_VERSION
FROM ${OPENPROJECT_IMAGE}:${OPENPROJECT_VERSION}

# If installing a local plugin (using `path:` in the copied `Gemfile.plugins`),
# you will have to copy the plugin code into the container here and use the
# path inside of the container. Say for `/app/vendor/plugins/openproject-slack`:
# COPY /path/to/my/local/openproject-slack /app/vendor/plugins/openproject-slack

COPY volumes/plugins/Gemfile.plugins /app/

# Work around sporadic autoload failures for this constant during db:migrate.
RUN f=/app/app/models/queries/projects/filters/custom_field_filter.rb; g=/app/app/models/queries/projects/filters/custom_field_context.rb; \
    if [ -f "$f" ] && [ -f "$g" ] && ! grep -q "require_relative 'custom_field_context'" "$f"; then \
      sed -i "1irequire_relative 'custom_field_context'" "$f"; \
    fi

# If the plugin uses any external NPM dependencies you have to install them here.
# RUN npm add npm <package-name>*

RUN bundle config unset deployment && bundle install && bundle config set deployment 'true'

# Work around grape eager-load ordering under Ruby 4.0 (Grape::Exceptions::Base referenced before it loads, breaking db:migrate).
RUN f=$(find /app/vendor/bundle -path '*grape*/lib/grape/exceptions/incompatible_option_values.rb' | head -1); \
    if [ -n "$f" ] && ! grep -q "require_relative 'base'" "$f"; then \
      sed -i "1irequire_relative 'base'" "$f"; \
    fi

RUN ./docker/prod/setup/precompile-assets.sh
