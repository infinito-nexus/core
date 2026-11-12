#!/bin/sh
# Param 1: root of the cloned hugoDocs site.
set -eu

src="$1"
design="$(dirname "$0")"

fail() {
	echo "upstream changed $1" >&2
	exit 1
}

edit() {
	grep -qF -- "$2" "${src}/$1" || fail "$1"
	sed -i "s|$2|$3|" "${src}/$1"
}

drop() {
	grep -qF -- "$2" "${src}/$1" || fail "$1"
	sed -i "/$2/d" "${src}/$1"
}

if [ -d "${design}/static" ]; then
	cp -R "${design}/static/." "${src}/static/"
	edit layouts/_partials/layouts/footer.html 'src="/images/hugo-logo-wide.svg"' 'src="/images/design-logo-frame.svg"'
	drop layouts/_partials/layouts/head/head.html 'rel=mask-icon'
fi

if [ -f "${design}/env" ]; then
	[ "$(grep -c '<title>' "${src}/layouts/baseof.html")" = 1 ] || fail layouts/baseof.html
	sed -i '/<title>/,/<\/title>/d' "${src}/layouts/baseof.html"
	edit layouts/_partials/layouts/header/header.html '>HUGO</a' '>{{ site.Title }}</a'
fi
