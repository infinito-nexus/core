#!/usr/bin/env bash
#
# Install a MediaWiki extension into the running container, idempotent.
# Runs ON THE HOSTING NODE (delegated); targets the local container via
# `container exec` / `container cp`.
#
# Required env, supplied by the calling Ansible task:
#   EXT_NAME                   extension name (subdir under extensions/)
#   EXT_TARBALL                node-side path to the downloaded .tar.gz
#   MEDIAWIKI_HTML_DIR         target directory inside the container
#   MEDIAWIKI_USER             unix user to own extracted files inside the container
#   MW_CID                     resolved container id (resolve_host_cid), local to this node
set -euo pipefail

ADDRESS="${MW_CID:?MW_CID env var (resolved container id) required}"

DST="${MEDIAWIKI_HTML_DIR}/extensions/${EXT_NAME}"

container exec "$ADDRESS" bash -lc "
  set -e
  if [ ! -f \"${DST}/extension.json\" ]; then
    rm -rf \"${DST}\" && mkdir -p \"${DST}\"
  fi
"

# nocheck: container-cp - EXT_TARBALL is downloaded on the node this script runs on
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
