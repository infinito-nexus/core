#!/bin/sh
# Args:
#   $1  the store AppRole
#   $2  the tenant mount
# Returns:
#   stdout: "<path> <value>", the one tenant secret the store wrote and erased again
set -eu

if [ "$#" -ne 2 ]; then
  echo "store-audit-probe.sh: expected <store role> <tenant mount>, got $# arguments" >&2
  exit 64
fi
role="$1"
mount="$2"

field() {
  printf '%s\n' "$minted" | sed -n "s/^ *\"$1\": \"\([^\"]*\)\".*/\1/p"
}

minted=$(bao write -format=json -f "auth/approle/role/$role/secret-id" num_uses=1 ttl=5m </dev/null)
accessor=$(field secret_id_accessor)
trap 'bao write -f "auth/approle/role/$role/secret-id-accessor/destroy" secret_id_accessor="$accessor" </dev/null >/dev/null 2>&1 || true' EXIT
role_id=$(bao read -field=role_id "auth/approle/role/$role/role-id" </dev/null)
token=$(field secret_id | bao write -field=token auth/approle/login role_id="$role_id" secret_id=-)
path="ws-audit-probe/$(date +%s)-$$"
value="store-audit-$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
BAO_TOKEN="$token" bao kv put -mount="$mount" "$path" value="$value" </dev/null >/dev/null
BAO_TOKEN="$token" bao kv metadata delete -mount="$mount" "$path" </dev/null >/dev/null
BAO_TOKEN="$token" bao token revoke -self </dev/null >/dev/null
printf '%s %s\n' "$path" "$value"
