#!/usr/bin/env bash
# Args:
#   none; any argument is refused
#
# Env (survey variables of the probe template, created only in test runtimes):
#   PROBE_SCRIPT   the bash text the Playwright spec runs inside the task;
#                  it prints only `PROBE <kind> <status>` lines, never a value
#   PROBE_ARGS     optional space-separated positional arguments of that text
set -euo pipefail

if [ "$#" -ne 0 ]; then
  printf 'probe.sh: takes no argument, got %s\n' "$#" >&2
  exit 2
fi
if [ -z "${PROBE_SCRIPT-}" ]; then
  printf 'probe.sh: PROBE_SCRIPT is required\n' >&2
  exit 2
fi
read -r -a probe_args <<<"${PROBE_ARGS-}"
exec bash -c "${PROBE_SCRIPT}" probe "${probe_args[@]}"
