#!/bin/sh
# @param $1 minimum free disc space (percent)
# @param $2 --force to run regardless of how much disc space is free
#
# All Ansible-resolved values are injected via systemd Environment= entries
# rendered by sys-service. See the role's tasks/01_core.yml for the
# `system_service_tpl_environment` block that populates them.
#
# Required environment:
#   SYS_SERVICE_CLEANUP_BACKUPS           systemd unit name to start for backup cleanup
#   SYS_SERVICE_CLEANUP_DOCKER            systemd unit name to start for docker cleanup
#   DEPLOYMENT_MODE                       'swarm' or 'compose'
#   BIN_RESOLVE_CONTAINER_ID              path to the resolver helper script
#   NEXTCLOUD_APPLICATION_CONTAINER       bare nextcloud container name (compose mode)
#   NEXTCLOUD_APPLICATION_STACK           swarm stack name for nextcloud
#   NEXTCLOUD_APPLICATION_SERVICE_KEY     swarm service key for nextcloud
#   MASTODON_APPLICATION_CONTAINER        bare mastodon container name (compose mode)
#   MASTODON_APPLICATION_STACK            swarm stack name for mastodon
#   MASTODON_APPLICATION_SERVICE_KEY      swarm service key for mastodon
#   MASTODON_CLEANUP_DAYS                 age cutoff for mastodon media cleanup (days)

# Print the address usable as `container exec <addr>`: in swarm mode the
# runtime container ID resolved by BIN_RESOLVE_CONTAINER_ID; otherwise
# the bare compose name. Systemd Environment= entries are literal text,
# so any subshell substitution must happen here at script-run time.
resolve_container_address() {
  stack="$1"
  service_key="$2"
  bare_name="$3"
  if [ "${DEPLOYMENT_MODE:-compose}" = "swarm" ]; then
    "${BIN_RESOLVE_CONTAINER_ID}" "${stack}" "${service_key}"
  else
    printf '%s' "${bare_name}"
  fi
}

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

    if [ -n "${NEXTCLOUD_APPLICATION_CONTAINER}" ] \
        && container ps -a --format '{{.Names}}' \
           | grep -Eq "(^|_)${NEXTCLOUD_APPLICATION_CONTAINER}(\.[0-9]+\.|$)" ; then
      nc_addr=$(resolve_container_address \
        "${NEXTCLOUD_APPLICATION_STACK}" \
        "${NEXTCLOUD_APPLICATION_SERVICE_KEY}" \
        "${NEXTCLOUD_APPLICATION_CONTAINER}") || exit 4
      echo "cleaning up docker nextcloud" &&
      container exec -u www-data "${nc_addr}" /var/www/html/occ files:cleanup || exit 4
      container exec -u www-data "${nc_addr}" /var/www/html/occ trashbin:cleanup --all-users || exit 5
      container exec -u www-data "${nc_addr}" /var/www/html/occ versions:cleanup || exit 6
    fi

    if [ -n "${MASTODON_APPLICATION_CONTAINER}" ] \
        && container ps -a --format '{{.Names}}' \
           | grep -Eq "(^|_)${MASTODON_APPLICATION_CONTAINER}(\.[0-9]+\.|$)" ; then
      md_addr=$(resolve_container_address \
        "${MASTODON_APPLICATION_STACK}" \
        "${MASTODON_APPLICATION_SERVICE_KEY}" \
        "${MASTODON_APPLICATION_CONTAINER}") || exit 8
      echo "Cleaning up Mastodon media cache (older than ${MASTODON_CLEANUP_DAYS} days)" &&
      container exec -u root "${md_addr}" bash -lc "bin/tootctl media remove --days=${MASTODON_CLEANUP_DAYS}" || exit 8
    fi
  fi

  if command -v pacman >/dev/null 2>&1 ; then
    echo "cleaning pacman cache" &&
    yes | pacman -Sc || exit 7
  fi

  echo "cleanup finished."
else
  echo "Sufficient disc space available."
  echo "To force the freeing of disc space pass the parameter --force."
fi
exit 0
