#!/bin/bash
# Serialize the stock image's first-boot copy+auto-install across replicas that
# share the /var/www/html NFS volume (mkdir is atomic on NFS: one leader runs it,
# the rest block on the ready marker). The setup only runs when $1 is apache2*/
# php-fpm, so the leader must drive it with `apache2 -v` (returns after setup) —
# a plain `true` skips the whole setup block and copies nothing.

target="/var/www/html"
lock="${target}/.infinito-init.lock"
ready="${target}/.infinito-init.ready"

if [ ! -e "${ready}" ] && [ ! -e "${target}/configuration.php" ]; then
  if mkdir "${lock}" 2>/dev/null; then
    /entrypoint.sh apache2 -v || true
    if [ -e "${target}/configuration.php" ]; then
      touch "${ready}"
    fi
  else
    tries=0
    while [ ! -e "${ready}" ] && [ ! -e "${target}/configuration.php" ] && [ "${tries}" -lt 300 ]; do
      sleep 2
      tries=$((tries + 1))
    done
  fi
fi

exec /entrypoint.sh "$@"
