#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  echo "erase-tree.sh: expected <mount> <prefix/>, got $# arguments" >&2
  exit 64
fi
mount="$1"
prefix="$2"
case "$prefix" in
  */) ;;
  *)
    echo "erase-tree.sh: the prefix must end with a slash: $prefix" >&2
    exit 64
    ;;
esac

keys() {
  if out=$(bao kv list -mount="$mount" "$1" 2>&1); then
    printf '%s\n' "$out" | awk 'NR == 1 && $1 != "Keys" { exit 1 } NR == 2 && $1 != "----" { exit 1 } NR > 2 { print }'
    return
  fi
  case "$out" in
    *"No value found"*) return 0 ;;
  esac
  printf '%s\n' "$out" >&2
  return 1
}

erase() {
  listed=$(keys "$1") || exit 1
  printf '%s\n' "$listed" | while IFS= read -r key; do
    [ -n "$key" ] || continue
    case "$key" in
      */) erase "$1$key" ;;
      *)
        bao kv metadata delete -mount="$mount" "$1$key" >/dev/null
        echo OPENBAO_CHANGED
        ;;
    esac
  done
}

erase "$prefix"
remaining=$(keys "$prefix") || exit 1
if [ -n "$remaining" ]; then
  echo "erase-tree.sh: keys remain below $mount/$prefix after the erasure" >&2
  exit 1
fi
