#!/bin/sh
# @param $1 minimum free disc space (percent)
# @param $2 --force to run regardless of how much disc space is free
#
# All Ansible-resolved values are injected via systemd Environment= entries
# rendered by sys-service. See the role's tasks/00_core.yml for the
# `system_service_tpl_environment` block that populates them.
#
# Required environment:
#   SYS_SERVICE_CLEANUP_BACKUPS           systemd unit name to start for backup cleanup
#   SYS_SERVICE_CLEANUP_DOCKER            systemd unit name to start for docker cleanup
#   SYS_SERVICE_CLEANUP_APPS_SCRIPT       sys-ctl-cln-apps dispatcher, run here in pressure mode
#   GARBAGE_COLLECTOR_MANIFEST_DIR        read by the dispatcher
#   GARBAGE_COLLECTOR_APP_TIMEOUT         read by the dispatcher
#   BIN_RESOLVE_CONTAINER_ID              read by the dispatcher

minimum_percent_cleanup_disc_space="$1"
force_freeing=false
echo "Checking free disc space..."
df
if [ $# -gt 0 ] && [ "$2" = "--force" ]; then
  echo "Forcing disc space freeing."
  force_freeing=true
fi
for disc_use_percent in $(df --output=pcent | sed 1d)
do
    disc_use_percent_number=$(echo "$disc_use_percent" | sed "s/%//")
    if [ "$disc_use_percent_number" -gt "$minimum_percent_cleanup_disc_space" ]; then
      echo "WARNING: ${disc_use_percent_number}% exceeds the limit of ${minimum_percent_cleanup_disc_space}%."
      force_freeing=true
    fi
done
if [ "$force_freeing" = true ]; then
  echo "cleaning up /tmp" &&
  find /tmp -type f -atime +10 -delete || exit 1
  if systemctl cat "${SYS_SERVICE_CLEANUP_BACKUPS}" >/dev/null 2>&1; then
    echo "cleaning up backups" &&
    systemctl start "${SYS_SERVICE_CLEANUP_BACKUPS}" || exit 2
  fi
  if command -v docker >/dev/null 2>&1 ; then
    if systemctl cat "${SYS_SERVICE_CLEANUP_DOCKER}" >/dev/null 2>&1; then
      echo "cleaning up docker (prune + anonymous volumes) via systemd service" &&
      systemctl start "${SYS_SERVICE_CLEANUP_DOCKER}" || exit 3
    fi

    if [ -x "${SYS_SERVICE_CLEANUP_APPS_SCRIPT}" ]; then
      echo "running the application garbage collectors in pressure mode" &&
      "${SYS_SERVICE_CLEANUP_APPS_SCRIPT}" pressure || exit 4
    fi
  fi

  if command -v pacman >/dev/null 2>&1 ; then
    echo "cleaning pacman cache"
    for pacman_cache_dir in $(pacman-conf CacheDir); do
      [ -w "${pacman_cache_dir}" ] || continue
      yes | pacman -Sc --cachedir "${pacman_cache_dir}" || exit 7
    done
  fi

  echo "cleanup finished."
else
  echo "Sufficient disc space available."
  echo "To force the freeing of disc space pass the parameter --force."
fi
exit 0
