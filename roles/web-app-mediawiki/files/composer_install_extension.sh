#!/usr/bin/env bash
#
# Run composer for one MediaWiki extension. Runs ON THE HOSTING NODE
# (delegated); copies install/helpers/ into the container and hands the work to
# composer_install.sh in there.
#
# The whole helper directory is copied rather than a list of names, so adding a
# helper means dropping a file into install/helpers/ and nothing else.
#
# Usage:
#   composer_install_extension.sh MW_USER HTML_DIR EXT_NAME EXT_BRANCH
#
# Required env, supplied by the calling Ansible task:
#   MW_CID                     resolved container id (resolve_host_cid), local to this node
#   MEDIAWIKI_EXT_HELPER_DIR   node-side directory holding the staged helpers
set -euo pipefail

MW_USER="$1"
HTML_DIR="$2"
EXT_NAME="$3"
EXT_BRANCH="$4"

CONTAINER="${MW_CID:?MW_CID env var (resolved container id) required}"
HELPER_DIR="${MEDIAWIKI_EXT_HELPER_DIR:?MEDIAWIKI_EXT_HELPER_DIR env var (staged helper directory) required}"

# nocheck: container-cp - the helpers are staged on the node this script runs on
container cp "${HELPER_DIR}/." "${CONTAINER}:/tmp/"

container exec -u "$MW_USER" "$CONTAINER" \
	bash /tmp/composer_install.sh "${HTML_DIR}/extensions/${EXT_NAME}" "$EXT_BRANCH" "$EXT_NAME"
