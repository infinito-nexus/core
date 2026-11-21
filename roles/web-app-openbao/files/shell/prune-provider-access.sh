#!/bin/sh
# Args:
#   $1   the task token auth mount
#   $2   ws-<id>, the workspace whose provider roles and policies are pruned
#   $@   after $2, the providers whose ws-<id>-provision-<provider> role and
#        policy stay; none for a workspace destroy
set -euf

if [ "$#" -lt 2 ]; then
  echo "prune-provider-access.sh: expected <mount> <ws-id> [provider ...], got $# arguments" >&2
  exit 64
fi
mount="$1"
workspace="$2"
shift 2
case "$workspace" in
  ws-?*) ;;
  *)
    echo "prune-provider-access.sh: not a workspace: $workspace" >&2
    exit 64
    ;;
esac
prefix="$workspace-provision-"
keep=" $* "

roles() {
  if out=$(bao list "auth/$mount/role" 2>&1); then
    printf '%s\n' "$out" | awk 'NR == 1 && $1 != "Keys" { exit 1 } NR == 2 && $1 != "----" { exit 1 } NR > 2 { print }'
    return
  fi
  case "$out" in
    *"No value found"*) return 0 ;;
  esac
  printf '%s\n' "$out" >&2
  return 1
}

dropped() {
  case "$1" in
    "$prefix"*) ;;
    *) return 1 ;;
  esac
  provider=${1#"$prefix"}
  case "$keep" in
    *" $provider "*) return 1 ;;
  esac
  return 0
}

listed=$(roles) || exit 1
for role in $listed; do
  if dropped "$role"; then
    bao delete "auth/$mount/role/$role" >/dev/null
    echo OPENBAO_CHANGED
  fi
done

policies=$(bao policy list)
for policy in $policies; do
  if dropped "$policy"; then
    bao policy delete "$policy" >/dev/null
    echo OPENBAO_CHANGED
  fi
done
