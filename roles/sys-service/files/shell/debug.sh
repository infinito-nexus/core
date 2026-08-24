#!/bin/sh
set -u

unit="${SYSTEM_SERVICE_DEBUG_UNIT:-}"
journal_lines="${SYSTEM_SERVICE_DEBUG_JOURNAL_LINES:-200}"
context="${SYSTEM_SERVICE_DEBUG_CONTEXT:-}"

if [ -z "$unit" ]; then
  echo "SYSTEM_SERVICE_DEBUG_UNIT is required" >&2
  exit 1
fi

print_section() {
  printf '\n=== %s ===\n' "$1"
}

run_section() {
  title="$1"
  shift

  print_section "$title"
  "$@" 2>&1
  rc=$?
  if [ "$rc" -ne 0 ]; then
    printf '\n(command failed with rc=%s)\n' "$rc"
  fi
}

if [ -n "$context" ]; then
  print_section "context"
  printf '%s\n' "$context"
fi

run_section \
  "systemctl show ${unit}" \
  systemctl --no-pager show \
  "--property=Id,Names,Description,LoadState,ActiveState,SubState,Result,UnitFileState,FragmentPath,SourcePath,ExecMainPID,ExecMainCode,ExecMainStatus,ExecStart,ExecStop" \
  "$unit"

run_section "systemctl status ${unit}" systemctl --no-pager --full status "$unit"
run_section "systemctl cat ${unit}" systemctl --no-pager cat "$unit"
run_section \
  "journalctl -u ${unit} (last ${journal_lines})" \
  journalctl --no-pager --no-hostname --full -xe -u "$unit" -n "$journal_lines"

main_pid="$(systemctl --no-pager show --property=ExecMainPID --value "$unit" 2>/dev/null || true)"
case "$main_pid" in
  ''|0)
    ;;
  *)
    if [ "$main_pid" -eq "$main_pid" ] 2>/dev/null; then
      run_section "ps -fp ${main_pid}" ps -fp "$main_pid"
    fi
    ;;
esac
