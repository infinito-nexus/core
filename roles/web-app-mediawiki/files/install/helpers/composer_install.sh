#!/usr/bin/env bash
#
# Install one MediaWiki extension's composer dependencies. Runs INSIDE the
# MediaWiki container, staged there by composer_install_extension.sh.
#
# Uses /tmp/composer for HOME and CACHE to avoid /var/www permission issues,
# and strips require-dev first (see strip_require_dev.php for why). Emits a
# stable status line for the caller's changed_when.
#
# Usage:
#   composer_install.sh EXT_DIR EXT_BRANCH EXT_NAME
set -euo pipefail

EXT_DIR="$1"
EXT_BRANCH="$2"
EXT_NAME="$3"

if [ ! -f "${EXT_DIR}/composer.json" ] || [ -f "${EXT_DIR}/vendor/autoload.php" ]; then
	echo "COMPOSER_PRESENT:${EXT_NAME}"
	exit 0
fi

install -d -m 0775 /tmp/composer/cache
export COMPOSER_HOME=/tmp/composer
export COMPOSER_CACHE_DIR=/tmp/composer/cache
export COMPOSER_ROOT_VERSION="dev-${EXT_BRANCH}"

cd "${EXT_DIR}"
php /tmp/strip_require_dev.php composer.json
composer install --no-dev -n --prefer-dist

echo "COMPOSER_INSTALLED:${EXT_NAME}"
