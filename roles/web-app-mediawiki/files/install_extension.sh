#!/usr/bin/env bash
#
# Install a MediaWiki extension into the running container, idempotent.
# Runs ON THE HOST; targets the container via `container exec` / `container cp`.
#
# Required env, supplied by the calling Ansible task:
#   EXT_NAME                   extension name (subdir under extensions/)
#   EXT_TARBALL                host-side path to the downloaded .tar.gz
#   MEDIAWIKI_HTML_DIR         target directory inside the container
#   MEDIAWIKI_USER             unix user to own extracted files inside the container
#   BARE_NAME                  bare compose container name
#   STACK                      swarm stack name
#   SERVICE_KEY                swarm service key
#   DEPLOYMENT_MODE            'swarm' or 'compose'
#   BIN_RESOLVE_CONTAINER_ID   path to resolver helper (swarm only)
set -euo pipefail

if [ "${DEPLOYMENT_MODE:-compose}" = "swarm" ]; then
  ADDRESS="$("$BIN_RESOLVE_CONTAINER_ID" "$STACK" "$SERVICE_KEY")"
else
  ADDRESS="$BARE_NAME"
fi

DST="${MEDIAWIKI_HTML_DIR}/extensions/${EXT_NAME}"

container exec "$ADDRESS" bash -lc "
  set -e
  if [ ! -f \"${DST}/extension.json\" ]; then
    rm -rf \"${DST}\" && mkdir -p \"${DST}\"
  fi
"

container cp "${EXT_TARBALL}" "${ADDRESS}:/tmp/${EXT_NAME}.tar.gz"

container exec "$ADDRESS" bash -lc "
  set -e
  if [ ! -f \"${DST}/extension.json\" ]; then
    tar -xzf /tmp/${EXT_NAME}.tar.gz -C \"${DST}\" --strip-components=1
    chown -R ${MEDIAWIKI_USER}:${MEDIAWIKI_USER} \"${DST}\"
    rm -f /tmp/${EXT_NAME}.tar.gz
    echo INSTALLED:${EXT_NAME}
  else
    rm -f /tmp/${EXT_NAME}.tar.gz
    echo PRESENT:${EXT_NAME}
  fi
"
