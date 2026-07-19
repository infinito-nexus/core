#!/usr/bin/env bash
# Idempotently ensure a Mattermost OAuth 2.0 service-provider application exists
# for the Nextcloud integration_mattermost connector and print its credentials.
#
# Runs INSIDE the Mattermost container (admin login + REST API via localhost).
# Emits exactly two machine-parseable lines on success:
#   CLIENT_ID=<id>
#   CLIENT_SECRET=<secret>
#
# Required env:
#   MM_LOCAL_URL   internal base url, e.g. http://localhost:8065
#   MM_TOKEN       admin API token (preferred; e.g. a mmctl-generated PAT). When
#                  set, MM_ADMIN_LOGIN/MM_ADMIN_PASS are ignored. Required when the
#                  admin is an SSO user (password login is disabled).
#   MM_ADMIN_LOGIN admin login id (email or username) — password-login fallback
#   MM_ADMIN_PASS  admin password — password-login fallback
#   MM_APP_NAME    OAuth app display name (stable identity key)
#   NC_BASE_URL    Nextcloud base url
#   NC_REDIRECT_PATH integration_mattermost oauth-redirect path (leading slash)
#   MM_HOMEPAGE    Nextcloud base url
set -euo pipefail

api="${MM_LOCAL_URL%/}/api/v4"

if [ -n "${MM_TOKEN:-}" ]; then
  token="${MM_TOKEN}"
else
  token="$(
    curl --connect-timeout 5 --max-time 30 -sS -i -X POST "${api}/users/login" \
      -H 'Content-Type: application/json' \
      -d "$(printf '{"login_id":"%s","password":"%s"}' "${MM_ADMIN_LOGIN}" "${MM_ADMIN_PASS}")" \
    | tr -d '\r' \
    | awk 'tolower($1)=="token:"{print $2; exit}'
  )"
fi

if [ -z "${token}" ]; then
  echo "mattermost authentication failed: no token available" >&2
  exit 1
fi

auth="Authorization: Bearer ${token}"

existing="$(
  curl --connect-timeout 5 --max-time 30 -sS -H "${auth}" "${api}/oauth/apps?page=0&per_page=200" \
  | python3 -c 'import json,os,sys
name=os.environ["MM_APP_NAME"]
try:
    apps=json.load(sys.stdin)
except Exception:
    apps=[]
for a in apps if isinstance(apps,list) else []:
    if a.get("name")==name:
        print("%s\t%s"%(a.get("id",""),a.get("client_secret","")))
        break
'
)"

if [ -n "${existing}" ]; then
  client_id="${existing%%	*}"
  client_secret="${existing#*	}"
else
  created="$(
    curl --connect-timeout 5 --max-time 30 -sS -X POST "${api}/oauth/apps" \
      -H "${auth}" -H 'Content-Type: application/json' \
      -d "$(python3 -c 'import json,os
base=os.environ["NC_BASE_URL"].rstrip("/")
path=os.environ["NC_REDIRECT_PATH"]
print(json.dumps({
  "name": os.environ["MM_APP_NAME"],
  "description": "Nextcloud integration_mattermost connector",
  "homepage": os.environ["MM_HOMEPAGE"],
  "callback_urls": [base+path, base+"/index.php"+path],
  "is_trusted": True,
}))')"
  )"
  client_id="$(printf '%s' "${created}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("id",""))')"
  client_secret="$(printf '%s' "${created}" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("client_secret",""))')"
fi

if [ -z "${client_id}" ] || [ -z "${client_secret}" ]; then
  echo "failed to obtain mattermost oauth app credentials" >&2
  exit 1
fi

printf 'CLIENT_ID=%s\n' "${client_id}"
printf 'CLIENT_SECRET=%s\n' "${client_secret}"
