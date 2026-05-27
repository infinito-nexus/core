#!/usr/bin/env bash
# Apply Zammad post-bootstrap configuration idempotently via the Rails
# console inside the zammad-railsserver container. Expects the following
# env vars exported in the caller's shell:
#   ZAMMAD_RAILS_CONTAINER    - container name (e.g. zammad-railsserver)
#   ZAMMAD_FQDN               - public hostname (e.g. helpdesk.infinito.example)
#   ZAMMAD_HTTP_TYPE          - "https" or "http"
#   OIDC_BUTTON_TEXT          - display label for the login button
#   OIDC_CLIENT_ID            - shared Keycloak client id (= SOFTWARE_DOMAIN)
#   OIDC_CLIENT_SECRET        - shared Keycloak client secret
#   OIDC_ISSUER_URL           - Keycloak realm issuer URL

set -euo pipefail

container exec "${ZAMMAD_RAILS_CONTAINER}" \
  bundle exec rails r "
    Setting.set('fqdn',      '${ZAMMAD_FQDN}')
    Setting.set('http_type', '${ZAMMAD_HTTP_TYPE}')
    Setting.set('auth_openid_connect', true)
    Setting.set('auth_openid_connect_credentials', {
      'display_name' => '${OIDC_BUTTON_TEXT}',
      'identifier'   => '${OIDC_CLIENT_ID}',
      'secret'       => '${OIDC_CLIENT_SECRET}',
      'issuer'       => '${OIDC_ISSUER_URL}',
      'scope'        => 'openid email profile',
      'uid_field'    => 'sub',
      'send_scope_to_token_endpoint' => true,
    })
  "
