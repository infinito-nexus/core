#!/bin/bash
# Provision Jellyfin auth non-interactively: complete the first-run wizard,
# install the LDAP + OIDC plugins via Jellyfin's own /Packages installer (so no
# curl/unzip is needed inside the container), then write the plugin config files
# and restart so they load.
#
# Runs on the DEPLOY HOST and talks to the published Jellyfin port (JELLYFIN_API);
# config files are written into the named volume via `container exec`.
#
# Verified against the upstream sources:
#   - LDAP plugin v23 PluginConfiguration (jellyfin-plugin-ldapauth, GUID
#     958aad66-3784-4d2a-b89a-a7b6fab6e25c): flat XmlSerializer schema below.
#   - SSO plugin v4.0.0.3 PluginConfiguration (9p4/jellyfin-plugin-sso):
#     OidConfigs is a SerializableDictionary<string,OidConfig>; the XML shape is
#     best-effort and MUST be confirmed on the first live deploy (the file is
#     XML-well-formedness checked before the reload, but not schema-validated).
set -euo pipefail

API="${JELLYFIN_API}"
CT="${JELLYFIN_NAME}"
CLIENT_HDR='X-Emby-Authorization: MediaBrowser Client="infinito", Device="ansible", DeviceId="infinito-deploy", Version="1.0.0"'

log() { echo "[jellyfin-auth] $*"; }

wait_up() {
  for _ in $(seq 1 60); do
    curl -fsS -o /dev/null "${API}/System/Info/Public" && return 0
    sleep 5
  done
  log "Jellyfin did not become ready at ${API}"; return 1
}

# --- first-run wizard (idempotent: ignore errors once setup is already done) ---
complete_wizard() {
  curl -fsS -X POST "${API}/Startup/Configuration" -H "Content-Type: application/json" -H "${CLIENT_HDR}" \
    -d '{"UICulture":"en-US","MetadataCountryCode":"US","PreferredMetadataLanguage":"en"}' >/dev/null 2>&1 || true
  curl -fsS "${API}/Startup/User" -H "${CLIENT_HDR}" >/dev/null 2>&1 || true
  curl -fsS -X POST "${API}/Startup/User" -H "Content-Type: application/json" -H "${CLIENT_HDR}" \
    -d "{\"Name\":\"${JELLYFIN_ADMIN_USERNAME}\",\"Password\":\"${JELLYFIN_ADMIN_PASSWORD}\"}" >/dev/null 2>&1 || true
  curl -fsS -X POST "${API}/Startup/RemoteAccess" -H "Content-Type: application/json" -H "${CLIENT_HDR}" \
    -d '{"EnableRemoteAccess":true,"EnableAutomaticPortMapping":false}' >/dev/null 2>&1 || true
  curl -fsS -X POST "${API}/Startup/Complete" -H "${CLIENT_HDR}" >/dev/null 2>&1 || true
}

get_token() {
  curl -fsS -X POST "${API}/Users/AuthenticateByName" -H "Content-Type: application/json" -H "${CLIENT_HDR}" \
    -d "{\"Username\":\"${JELLYFIN_ADMIN_USERNAME}\",\"Pw\":\"${JELLYFIN_ADMIN_PASSWORD}\"}" \
    | sed -n 's/.*"AccessToken":"\([^"]*\)".*/\1/p'
}

install_plugin() { # $1 = url-encoded package name
  if curl -fsS -X POST "${API}/Packages/Installed/${1}" -H "Authorization: MediaBrowser Token=\"${TOKEN}\"" >/dev/null 2>&1; then
    log "requested install: ${1}"
  else
    log "install request failed (already present?): ${1}"
  fi
}

write_config() { # $1 = filename, stdin = content
  container exec -i "${CT}" sh -c "mkdir -p /config/plugins/configurations && cat > /config/plugins/configurations/$1"
}

wait_up
complete_wizard
TOKEN="$(get_token || true)"

if [ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ]; then
  # Register the SSO plugin manifest so Jellyfin can resolve + install it.
  curl -fsS -X POST "${API}/Repositories" -H "Content-Type: application/json" \
    -H "Authorization: MediaBrowser Token=\"${TOKEN}\"" \
    -d "[{\"Name\":\"jellyfin-plugin-sso\",\"Url\":\"${JELLYFIN_SSO_PLUGIN_MANIFEST}\",\"Enabled\":true}]" >/dev/null 2>&1 || true
fi

[ -n "${TOKEN:-}" ] && [ "${JELLYFIN_LDAP_ENABLED}" = "true" ] && install_plugin "LDAP%20Authentication"
[ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ] && install_plugin "SSO%20Authentication"

# Let Jellyfin finish downloading the plugins, then restart so they load.
sleep 10
container restart "${CT}" >/dev/null
wait_up

# --- LDAP plugin config (flat XmlSerializer schema — verified v23) ---
if [ "${JELLYFIN_LDAP_ENABLED}" = "true" ]; then
  write_config "LDAP-Auth.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<PluginConfiguration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <LdapServer>${JELLYFIN_LDAP_SERVER}</LdapServer>
  <LdapPort>${JELLYFIN_LDAP_PORT}</LdapPort>
  <UseSsl>false</UseSsl>
  <UseStartTls>false</UseStartTls>
  <SkipSslVerify>false</SkipSslVerify>
  <LdapBindUser>${JELLYFIN_LDAP_BIND_DN}</LdapBindUser>
  <LdapBindPassword>${JELLYFIN_LDAP_BIND_PASSWORD}</LdapBindPassword>
  <LdapBaseDn>${JELLYFIN_LDAP_BASE_DN}</LdapBaseDn>
  <LdapSearchFilter>(objectClass=inetOrgPerson)</LdapSearchFilter>
  <LdapSearchAttributes>uid, cn, mail, displayName</LdapSearchAttributes>
  <CreateUsersFromLdap>true</CreateUsersFromLdap>
  <LdapUidAttribute>${JELLYFIN_LDAP_UID_ATTR}</LdapUidAttribute>
  <LdapUsernameAttribute>${JELLYFIN_LDAP_UID_ATTR}</LdapUsernameAttribute>
  <LdapPasswordAttribute>userPassword</LdapPasswordAttribute>
  <EnableAllFolders>true</EnableAllFolders>
</PluginConfiguration>
XML
  container exec -i "${CT}" sh -c "python3 -c \"import xml.dom.minidom,sys; xml.dom.minidom.parse('/config/plugins/configurations/LDAP-Auth.xml')\"" 2>/dev/null \
    || log "WARN: LDAP-Auth.xml not parseable by python (still written); confirm on live deploy"
fi

# --- OIDC/SSO plugin config (best-effort SerializableDictionary shape) ---
if [ "${JELLYFIN_SSO_ENABLED}" = "true" ]; then
  write_config "SSO-Auth.xml" <<XML
<?xml version="1.0" encoding="utf-8"?>
<PluginConfiguration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:xsd="http://www.w3.org/2001/XMLSchema">
  <SamlConfigs />
  <OidConfigs>
    <item>
      <key><string>Keycloak</string></key>
      <value>
        <OidConfig>
          <OidEndpoint>${JELLYFIN_OIDC_ISSUER}</OidEndpoint>
          <OidClientId>${JELLYFIN_OIDC_CLIENT_ID}</OidClientId>
          <OidSecret>${JELLYFIN_OIDC_CLIENT_SECRET}</OidSecret>
          <Enabled>true</Enabled>
          <EnableAuthorization>false</EnableAuthorization>
          <EnableAllFolders>true</EnableAllFolders>
          <EnableFolderRoles>false</EnableFolderRoles>
          <EnableLiveTv>false</EnableLiveTv>
          <EnableLiveTvManagement>false</EnableLiveTvManagement>
          <Roles />
          <AdminRoles />
          <RoleClaim>realm_access.roles</RoleClaim>
          <OidScopes>
            <string>openid</string>
            <string>profile</string>
            <string>email</string>
          </OidScopes>
          <DefaultUsernameClaim>preferred_username</DefaultUsernameClaim>
        </OidConfig>
      </value>
    </item>
  </OidConfigs>
</PluginConfiguration>
XML
  container exec -i "${CT}" sh -c "python3 -c \"import xml.dom.minidom,sys; xml.dom.minidom.parse('/config/plugins/configurations/SSO-Auth.xml')\"" 2>/dev/null \
    || log "WARN: SSO-Auth.xml not parseable by python (still written); confirm on live deploy"
fi

container restart "${CT}" >/dev/null
log "auth provisioning complete"
