#!/bin/bash
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

seed_admin_and_get_token() {
  for _ in $(seq 1 40); do
    complete_wizard
    TOKEN="$(get_token || true)"
    [ -n "${TOKEN:-}" ] && return 0
    sleep 3
  done
  return 1
}

install_plugin() {
  if curl -fsS -X POST "${API}/Packages/Installed/${1}" -H "Authorization: MediaBrowser Token=\"${TOKEN}\"" >/dev/null 2>&1; then
    log "requested install: ${1}"
  else
    log "install request failed (already present?): ${1}"
  fi
}

install_ldap_plugin() {
  : "${JELLYFIN_LDAP_PLUGIN_URL:?missing (set via meta/addons/ldap-authentication.yml)}"
  : "${JELLYFIN_LDAP_PLUGIN_VERSION:?missing (set via meta/addons/ldap-authentication.yml)}"
  local tmp
  tmp="$(mktemp -d)"
  if ! curl -fsSL -o "${tmp}/ldap.zip" "${JELLYFIN_LDAP_PLUGIN_URL}"; then
    log "ERROR: failed to download LDAP plugin from ${JELLYFIN_LDAP_PLUGIN_URL}"
    rm -rf "${tmp}"; return 1
  fi
  if command -v md5sum >/dev/null 2>&1 \
     && ! echo "${JELLYFIN_LDAP_PLUGIN_MD5}  ${tmp}/ldap.zip" | md5sum -c - >/dev/null 2>&1; then
    log "ERROR: LDAP plugin checksum mismatch"; rm -rf "${tmp}"; return 1
  fi
  python3 -m zipfile -e "${tmp}/ldap.zip" "${tmp}/ldap"
  container exec "${CT}" mkdir -p "/config/plugins/LDAP Authentication_${JELLYFIN_LDAP_PLUGIN_VERSION}"
  container cp "${tmp}/ldap/." "${CT}:/config/plugins/LDAP Authentication_${JELLYFIN_LDAP_PLUGIN_VERSION}"
  rm -rf "${tmp}"
  log "installed LDAP plugin ${JELLYFIN_LDAP_PLUGIN_VERSION} from GitHub release"
}

write_config() {
  container exec -i "${CT}" sh -c "mkdir -p /config/plugins/configurations && cat > /config/plugins/configurations/$1"
}

wait_up
seed_admin_and_get_token || log "WARN: admin token unavailable after wizard retries; SSO manifest + login-button branding will be skipped"

if [ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ]; then
  curl -fsS -X POST "${API}/Repositories" -H "Content-Type: application/json" \
    -H "Authorization: MediaBrowser Token=\"${TOKEN}\"" \
    -d "[{\"Name\":\"jellyfin-plugin-sso\",\"Url\":\"${JELLYFIN_SSO_PLUGIN_MANIFEST}\",\"Enabled\":true}]" >/dev/null 2>&1 || true
fi

[ "${JELLYFIN_LDAP_ENABLED}" = "true" ] && install_ldap_plugin
[ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ] && install_plugin "SSO%20Authentication"

sleep 10
container restart "${CT}" >/dev/null
wait_up

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

if [ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ]; then
  SSO_PLUGIN_GUID="505ce9d1-d916-42fa-86ca-673ef241d7df"
  if curl -fsS -X POST "${API}/Plugins/${SSO_PLUGIN_GUID}/Configuration" \
      -H "Content-Type: application/json" \
      -H "Authorization: MediaBrowser Token=\"${TOKEN}\"" --data @- >/dev/null 2>&1 <<JSON
{
  "SamlConfigs": {},
  "OidConfigs": {
    "Keycloak": {
      "OidEndpoint": "${JELLYFIN_OIDC_ISSUER}",
      "OidClientId": "${JELLYFIN_OIDC_CLIENT_ID}",
      "OidSecret": "${JELLYFIN_OIDC_CLIENT_SECRET}",
      "Enabled": true,
      "EnableAuthorization": false,
      "EnableAllFolders": true,
      "EnabledFolders": [],
      "Roles": [],
      "AdminRoles": [],
      "EnableFolderRoles": false,
      "EnableLiveTv": false,
      "EnableLiveTvManagement": false,
      "LiveTvRoles": [],
      "LiveTvManagementRoles": [],
      "FolderRoleMapping": [],
      "RoleClaim": "realm_access.roles",
      "OidScopes": ["openid", "profile", "email"],
      "DefaultUsernameClaim": "preferred_username",
      "DisablePushedAuthorization": true,
      "SchemeOverride": "https"
    }
  }
}
JSON
  then
    log "configured SSO OIDC provider (Keycloak)"
  else
    log "WARN: failed to configure SSO OIDC provider"
  fi
fi

if [ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ]; then
  if curl -fsS -X POST "${API}/System/Configuration/branding" -H "Content-Type: application/json" \
      -H "Authorization: MediaBrowser Token=\"${TOKEN}\"" \
      -d '{"LoginDisclaimer":"<form action=\"/sso/OID/start/Keycloak\"><button class=\"raised block emby-button button-submit\">Sign in with Keycloak</button></form>","CustomCss":"a.raised.emby-button { padding: 0.9em 1em; color: inherit !important; } .disclaimerContainer { display: block; }","SplashscreenEnabled":false}' >/dev/null 2>&1; then
    log "configured SSO login button via branding"
  else
    log "WARN: failed to set SSO login branding"
  fi
fi

container restart "${CT}" >/dev/null
log "auth provisioning complete"
