#!/usr/bin/env bash
# Bring nfs-ganesha into a serving state and prove it, or fail with the reason.
#
# Params:
#   $1  systemd unit name (without .service)
#   $2  TCP port that proves the server is listening
#   $3  seconds to wait for that port
#   $4  "restart" after a config change, "start" otherwise
#
# Exit: 0 once the port accepts a connection, 1 with the unit's status and
#       journal on stderr.
# Stdout: the word CHANGED when the unit's state was actually altered.
set -u

unit="$1"
port="$2"
budget="$3"
action="$4"

was_active=false
if systemctl is-active --quiet "$unit"; then
    was_active=true
fi

systemctl_output="$(systemctl "$action" "$unit" 2>&1)"
systemctl_rc=$?

if [ "$action" = "restart" ] || [ "$was_active" = false ]; then
    echo CHANGED
fi

deadline=$(( $(date +%s) + budget ))
while [ "$(date +%s)" -lt "$deadline" ]; do
    if (exec 3<>"/dev/tcp/127.0.0.1/${port}") 2>/dev/null; then
        exec 3>&- 3<&-
        exit 0
    fi
    sleep 1
done

{
    echo "nfs-ganesha did not listen on ${port} within ${budget}s after '${action}'."
    echo "systemctl ${action} exited ${systemctl_rc}: ${systemctl_output}"
    echo "--- systemctl status ---"
    systemctl status "$unit" --no-pager --lines=20 2>&1
    echo "--- journal ---"
    journalctl -u "$unit" --no-pager --lines=40 2>&1
} >&2
exit 1
