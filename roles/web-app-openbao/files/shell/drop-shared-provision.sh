#!/bin/sh
# Args:
#   $1   the task token auth mount; each ws-<id>-provision role there that
#        holds another policy than its own or binds other than the two
#        templates unlock and dns goes, and so does each ws-<id>-transit-child
#        token role that allows other than ws-<id>-transit, until workspace
#        apply writes them again
set -euf

if [ "$#" -ne 1 ]; then
  echo "drop-shared-provision.sh: expected <mount>, got $# arguments" >&2
  exit 64
fi
mount="$1"

listing() {
  if out=$(bao list "$1" 2>&1); then
    printf '%s\n' "$out" | awk 'NR == 1 && $1 != "Keys" { exit 1 } NR == 2 && $1 != "----" { exit 1 } NR > 2 { print }'
    return
  fi
  case "$out" in
    *"No value found"*) return 0 ;;
  esac
  printf '%s\n' "$out" >&2
  return 1
}

if out=$(bao policy read provision-shared 2>&1); then
  bao policy delete provision-shared >/dev/null
  echo OPENBAO_CHANGED
else
  case "$out" in
    *"No policy named"*) ;;
    *)
      printf '%s\n' "$out" >&2
      exit 1
      ;;
  esac
fi

listed=$(listing "auth/$mount/role") || exit 1
for role in $listed; do
  case "$role" in
    ws-?*-provision) ;;
    *) continue ;;
  esac
  path="auth/$mount/role/$role"
  held=$(bao read -field=token_policies "$path")
  claims=$(bao read -field=bound_claims "$path")
  bound=$(printf '%s\n' "$claims" | sed -n 's/.*template_id:\[\([^]]*\)\].*/\1/p' | awk '{ print NF }')
  if [ "$held" != "[$role]" ] || [ "$bound" != 2 ]; then
    bao delete "$path" >/dev/null
    echo OPENBAO_CHANGED
  fi
done

listed=$(listing auth/token/roles) || exit 1
for role in $listed; do
  case "$role" in
    ws-?*-transit-child) ;;
    *) continue ;;
  esac
  allowed=$(bao read -field=allowed_policies "auth/token/roles/$role")
  if [ "$allowed" != "[${role%-child}]" ]; then
    bao delete "auth/token/roles/$role" >/dev/null
    echo OPENBAO_CHANGED
  fi
done
