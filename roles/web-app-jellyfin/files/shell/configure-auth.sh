#!/bin/bash
# Param: stdin  line 1 the admin password, line 2 the LDAP bind password,
#               line 3 the OIDC client secret (empty when the feature is off)
set -euo pipefail

IFS= read -r JELLYFIN_ADMIN_PASSWORD
IFS= read -r JELLYFIN_LDAP_BIND_PASSWORD
IFS= read -r JELLYFIN_OIDC_CLIENT_SECRET
: "${JELLYFIN_ADMIN_PASSWORD:?the admin password arrives on stdin}"
if [ "${JELLYFIN_LDAP_ENABLED}" = "true" ]; then : "${JELLYFIN_LDAP_BIND_PASSWORD:?the LDAP bind password arrives on stdin}"; fi
if [ "${JELLYFIN_SSO_ENABLED}" = "true" ]; then : "${JELLYFIN_OIDC_CLIENT_SECRET:?the OIDC client secret arrives on stdin}"; fi

API="${JELLYFIN_API}"
CT="${JELLYFIN_CT}"
CURL="container exec -i ${CT} curl --connect-timeout 5 --max-time 30"
HOST_CURL="curl --connect-timeout 5 --max-time 30"
PHASE="${JELLYFIN_PHASE}"
CLIENT_HDR='X-Emby-Authorization: MediaBrowser Client="infinito", Device="ansible", DeviceId="infinito-deploy", Version="1.0.0"'

log() { echo "[jellyfin-auth] $*"; }

json_escape() {
  local value="${1//\\/\\\\}"
  printf '%s' "${value//\"/\\\"}"
}

post_json() {
  local url="$1" body="$2"
  shift 2
  printf '%s' "${body}" | ${CURL} -fsS -X POST "${url}" -H "Content-Type: application/json" "$@" --data-binary @-
}

AUTH_HEADER_FILE=""
use_token() {
  if [ -z "${AUTH_HEADER_FILE}" ]; then
    AUTH_HEADER_FILE="$(container exec "${CT}" mktemp)" || return 1
  fi
  printf 'Authorization: MediaBrowser Token="%s"\n' "$1" \
    | container exec -i "${CT}" sh -c "cat > ${AUTH_HEADER_FILE}"
}
trap '[ -z "${AUTH_HEADER_FILE}" ] || container exec "${CT}" rm -f "${AUTH_HEADER_FILE}" >/dev/null 2>&1 || true' EXIT  # nocheck: shell-or-true -- best-effort removal of a temp file; the container may already be gone

wait_up() {
  for _ in $(seq 1 60); do
    ${CURL} -fsS -o /dev/null "${API}/System/Info/Public" && return 0
    sleep 5
  done
  log "Jellyfin did not become ready at ${API}"; return 1
}

complete_wizard() {
  ${CURL} -fsS -X POST "${API}/Startup/Configuration" -H "Content-Type: application/json" -H "${CLIENT_HDR}" \
    -d '{"UICulture":"en-US","MetadataCountryCode":"US","PreferredMetadataLanguage":"en"}' >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  ${CURL} -fsS "${API}/Startup/User" -H "${CLIENT_HDR}" >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  post_json "${API}/Startup/User" \
    "{\"Name\":\"$(json_escape "${JELLYFIN_ADMIN_USERNAME}")\",\"Password\":\"$(json_escape "${JELLYFIN_ADMIN_PASSWORD}")\"}" \
    -H "${CLIENT_HDR}" >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  ${CURL} -fsS -X POST "${API}/Startup/RemoteAccess" -H "Content-Type: application/json" -H "${CLIENT_HDR}" \
    -d '{"EnableRemoteAccess":true,"EnableAutomaticPortMapping":false}' >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
  ${CURL} -fsS -X POST "${API}/Startup/Complete" -H "${CLIENT_HDR}" >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
}

authenticate() {
  post_json "${API}/Users/AuthenticateByName" \
    "{\"Username\":\"$(json_escape "${JELLYFIN_ADMIN_USERNAME}")\",\"Pw\":\"$(json_escape "${1-${JELLYFIN_ADMIN_PASSWORD}}")\"}" \
    -H "${CLIENT_HDR}"
}

token_of() { sed -n 's/.*"AccessToken":"\([^"]*\)".*/\1/p'; }
user_id_of() { sed -n 's/.*"User":{[^}]*"Id":"\([^"]*\)".*/\1/p'; }

get_token() {
  authenticate | token_of
}

realign_admin_password() {
  local pin pin_token user_id auth
  ${CURL} -fsS -X POST "${API}/Users/ForgotPassword" -H "Content-Type: application/json" -H "${CLIENT_HDR}" \
    -d "{\"EnteredUsername\":\"${JELLYFIN_ADMIN_USERNAME}\"}" >/dev/null || {
    log "ERROR: Jellyfin refused the password reset request"
    return 1
  }
  pin="$(container exec "${CT}" sh -c 'cat /config/passwordreset*.json 2>/dev/null' \
    | sed -n 's/.*"Pin":"\([^"]*\)".*/\1/p' | head -n1)" || pin=""
  if [ -z "${pin}" ]; then
    log "ERROR: Jellyfin accepted the reset request but wrote no pin file"
    return 1
  fi
  post_json "${API}/Users/ForgotPassword/Pin" "{\"Pin\":\"$(json_escape "${pin}")\"}" -H "${CLIENT_HDR}" >/dev/null || {
    log "ERROR: Jellyfin rejected the reset pin"
    return 1
  }
  auth="$(authenticate "${pin}")" || auth=""
  pin_token="$(printf '%s' "${auth}" | token_of)"
  user_id="$(printf '%s' "${auth}" | user_id_of)"
  if [ -z "${pin_token}" ] || [ -z "${user_id}" ]; then
    log "ERROR: redeeming the reset pin cleared the stored password and the administrator still does not authenticate; the account is now WITHOUT a password"
    return 1
  fi
  use_token "${pin_token}" || {
    log "ERROR: could not stage the reset session token inside the container; the administrator is now WITHOUT a password"
    return 1
  }
  post_json "${API}/Users/${user_id}/Password" \
    "{\"CurrentPw\":\"$(json_escape "${pin}")\",\"NewPw\":\"$(json_escape "${JELLYFIN_ADMIN_PASSWORD}")\"}" \
    -H "@${AUTH_HEADER_FILE}" >/dev/null || {
    log "ERROR: the password change was rejected; the reset already cleared the old one, so the administrator is now WITHOUT a password"
    return 1
  }
  log "realigned the administrator password with the one this deployment declares"
}

seed_admin_and_get_token() {
  for _ in $(seq 1 40); do
    complete_wizard
    TOKEN="$(get_token || true)"
    if [ -n "${TOKEN:-}" ]; then
      use_token "${TOKEN}" || return 1
      return 0
    fi
    sleep 3
  done
  realign_admin_password || return 1
  TOKEN="$(get_token)" || TOKEN=""
  [ -n "${TOKEN:-}" ] || return 1
  use_token "${TOKEN}"
}

install_plugin() {
  if ${CURL} -fsS -X POST "${API}/Packages/Installed/${1}" -H "@${AUTH_HEADER_FILE}" >/dev/null 2>&1; then
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
  if ! ${HOST_CURL} --max-time 300 -fsSL -o "${tmp}/ldap.zip" "${JELLYFIN_LDAP_PLUGIN_URL}"; then
    log "ERROR: failed to download LDAP plugin from ${JELLYFIN_LDAP_PLUGIN_URL}"
    rm -rf "${tmp}"; return 1
  fi
  if command -v md5sum >/dev/null 2>&1 \
     && ! echo "${JELLYFIN_LDAP_PLUGIN_MD5}  ${tmp}/ldap.zip" | md5sum -c - >/dev/null 2>&1; then
    log "ERROR: LDAP plugin checksum mismatch"; rm -rf "${tmp}"; return 1
  fi
  python3 -m zipfile -e "${tmp}/ldap.zip" "${tmp}/ldap"
  container exec "${CT}" mkdir -p "/config/plugins/LDAP Authentication_${JELLYFIN_LDAP_PLUGIN_VERSION}"
  # nocheck: container-cp - plugin payload is staged in a script-local tmp dir on the same node
  container cp "${tmp}/ldap/." "${CT}:/config/plugins/LDAP Authentication_${JELLYFIN_LDAP_PLUGIN_VERSION}"
  rm -rf "${tmp}"
  log "installed LDAP plugin ${JELLYFIN_LDAP_PLUGIN_VERSION} from GitHub release"
}

write_config() {
  container exec -i "${CT}" sh -c "mkdir -p /config/plugins/configurations && cat > /config/plugins/configurations/$1"
}

if [ "${PHASE}" = "install" ]; then

wait_up
seed_admin_and_get_token || {
  log "ERROR: the administrator cannot authenticate after wizard retries; the deployed password does not match the running server"
  exit 1
}

if [ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ]; then
  ${CURL} -fsS -X POST "${API}/Repositories" -H "Content-Type: application/json" \
    -H "@${AUTH_HEADER_FILE}" \
    -d "[{\"Name\":\"jellyfin-plugin-sso\",\"Url\":\"${JELLYFIN_SSO_PLUGIN_MANIFEST}\",\"Enabled\":true}]" >/dev/null 2>&1 || true  # nocheck: shell-or-true -- grandfathered: worked in practice; TODO: sharpen to catch only the exact tolerated error
fi

[ "${JELLYFIN_LDAP_ENABLED}" = "true" ] && install_ldap_plugin
[ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ] && install_plugin "SSO%20Authentication"

sleep 10
log "plugin install phase complete (restart is driven by the calling task)"
exit 0

fi

if [ "${PHASE}" != "configure" ]; then
  log "ERROR: unknown JELLYFIN_PHASE '${PHASE}' (expected install|configure)"
  exit 1
fi

wait_up
seed_admin_and_get_token || {
  log "ERROR: the administrator cannot authenticate after wizard retries; the deployed password does not match the running server"
  exit 1
}

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
  <LdapSearchFilter>${JELLYFIN_LDAP_SEARCH_FILTER}</LdapSearchFilter>
  <LdapSearchAttributes>${JELLYFIN_LDAP_SEARCH_ATTRIBUTES}</LdapSearchAttributes>
  <LdapAdminFilter>${JELLYFIN_LDAP_ADMIN_FILTER}</LdapAdminFilter>
  <EnableLdapAdminFilterMemberUid>false</EnableLdapAdminFilterMemberUid>
  <CreateUsersFromLdap>true</CreateUsersFromLdap>
  <AllowPassChange>false</AllowPassChange>
  <LdapUidAttribute>${JELLYFIN_LDAP_UID_ATTR}</LdapUidAttribute>
  <LdapUsernameAttribute>${JELLYFIN_LDAP_UID_ATTR}</LdapUsernameAttribute>
  <LdapPasswordAttribute>${JELLYFIN_LDAP_PASSWORD_ATTR}</LdapPasswordAttribute>
  <EnableLdapProfileImageSync>true</EnableLdapProfileImageSync>
  <LdapProfileImageAttribute>${JELLYFIN_LDAP_PHOTO_ATTR}</LdapProfileImageAttribute>
  <EnableAllFolders>true</EnableAllFolders>
</PluginConfiguration>
XML
  container exec -i "${CT}" sh -c "python3 -c \"import xml.dom.minidom,sys; xml.dom.minidom.parse('/config/plugins/configurations/LDAP-Auth.xml')\"" 2>/dev/null \
    || log "WARN: LDAP-Auth.xml not parseable by python (still written); confirm on live deploy"
fi

if [ -n "${TOKEN:-}" ] && [ "${JELLYFIN_SSO_ENABLED}" = "true" ]; then
  SSO_PLUGIN_GUID="505ce9d1-d916-42fa-86ca-673ef241d7df"
  if ${CURL} -fsS -X POST "${API}/Plugins/${SSO_PLUGIN_GUID}/Configuration" \
      -H "Content-Type: application/json" \
      -H "@${AUTH_HEADER_FILE}" --data @- >/dev/null 2>&1 <<JSON
{
  "SamlConfigs": {},
  "OidConfigs": {
    "Keycloak": {
      "OidEndpoint": "${JELLYFIN_OIDC_ISSUER}",
      "OidClientId": "${JELLYFIN_OIDC_CLIENT_ID}",
      "OidSecret": "${JELLYFIN_OIDC_CLIENT_SECRET}",
      "Enabled": true,
      "EnableAuthorization": true,
      "EnableAllFolders": true,
      "EnabledFolders": [],
      "Roles": [],
      "AdminRoles": ["${JELLYFIN_OIDC_ADMIN_ROLE}"],
      "EnableFolderRoles": false,
      "EnableLiveTv": false,
      "EnableLiveTvManagement": false,
      "LiveTvRoles": [],
      "LiveTvManagementRoles": [],
      "FolderRoleMapping": [],
      "RoleClaim": "${JELLYFIN_OIDC_ROLE_CLAIM}",
      "OidScopes": ["openid", "profile", "email"],
      "DefaultUsernameClaim": "${JELLYFIN_OIDC_USERNAME_CLAIM}",
      "DisablePushedAuthorization": true,
      "DisableHttps": ${JELLYFIN_OIDC_DISABLE_HTTPS}
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

LOGIN_DISCLAIMER=""
LOGIN_CSS=""
if [ "${JELLYFIN_SSO_ENABLED}" = "true" ] && [ "${JELLYFIN_LOGIN_SSO_ENABLED}" = "true" ]; then
  LOGIN_DISCLAIMER='<form action=\"/sso/OID/start/Keycloak\"><button class=\"raised block emby-button button-submit\">Sign in with Keycloak</button></form>'
  LOGIN_CSS='a.raised.emby-button { padding: 0.9em 1em; color: inherit !important; } .disclaimerContainer { display: block; }'
fi
if [ "${JELLYFIN_LOGIN_FORM_ENABLED}" != "true" ]; then
  LOGIN_CSS="${LOGIN_CSS} #loginPage .manualLoginForm, #loginPage .visualLoginForm, #loginPage .btnManual, #loginPage .btnQuick, #loginPage .btnForgotPassword { display: none !important; }"
fi

if [ -n "${TOKEN:-}" ] && { [ "${JELLYFIN_SSO_ENABLED}" = "true" ] || [ "${JELLYFIN_LOGIN_FORM_ENABLED}" != "true" ]; }; then
  if ${CURL} -fsS -X POST "${API}/System/Configuration/branding" -H "Content-Type: application/json" \
      -H "@${AUTH_HEADER_FILE}" --data @- >/dev/null 2>&1 <<JSON
{"LoginDisclaimer":"${LOGIN_DISCLAIMER}","CustomCss":"${LOGIN_CSS}","SplashscreenEnabled":false}
JSON
  then
    log "configured the login methods of the sign-in page via branding"
  else
    log "WARN: failed to set the login branding"
  fi
fi

log "auth provisioning complete (final restart is driven by the calling task)"
