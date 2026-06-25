#!/usr/bin/env bash
#
# Run `composer install --no-dev` for one MediaWiki extension when its
# `vendor/autoload.php` is missing. Uses /tmp/composer for HOME/CACHE
# to avoid /var/www permission issues. Emits a stable status line for
# changed_when.
#
# Usage:
#   composer_install_extension.sh MW_USER HTML_DIR EXT_NAME EXT_BRANCH
#
# Required env, supplied by the calling Ansible task (mode-aware container
# addressing, identical to install_extension.sh):
#   BARE_NAME                  bare compose container name
#   STACK                      swarm stack name
#   SERVICE_KEY                swarm service key
#   DEPLOYMENT_MODE            'swarm' or 'compose'
#   BIN_RESOLVE_CONTAINER_ID   path to resolver helper (swarm only)
set -euo pipefail

MW_USER="$1"
HTML_DIR="$2"
EXT_NAME="$3"
EXT_BRANCH="$4"

if [ "${DEPLOYMENT_MODE:-compose}" = "swarm" ]; then
  CONTAINER="$("$BIN_RESOLVE_CONTAINER_ID" "$STACK" "$SERVICE_KEY")"
else
  CONTAINER="$BARE_NAME"
fi

container exec -u "$MW_USER" "$CONTAINER" bash -lc "
    set -e
    d='$HTML_DIR/extensions/$EXT_NAME'
    if [ -f \"\$d/composer.json\" ] && [ ! -f \"\$d/vendor/autoload.php\" ]; then
        install -d -m 0775 /tmp/composer/cache
        export COMPOSER_HOME=/tmp/composer
        export COMPOSER_CACHE_DIR=/tmp/composer/cache
        export COMPOSER_ROOT_VERSION=dev-$EXT_BRANCH
        cd \"\$d\"
        composer install --no-dev -n --prefer-dist
        echo 'COMPOSER_INSTALLED:$EXT_NAME'
    else
        echo 'COMPOSER_PRESENT:$EXT_NAME'
    fi
"
