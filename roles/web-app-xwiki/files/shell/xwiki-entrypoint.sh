#!/bin/sh
set -e

# The stock entrypoint restores WEB-INF/xwiki.properties from the data volume and
# then rewrites it in place; a read-only mount over WEB-INF (the swarm config
# object) makes that writeback fail. Feed our config through the data volume and
# let the stock entrypoint own WEB-INF.
if [ -f /etc/infinito/xwiki.properties ]; then
	mkdir -p /usr/local/xwiki/data
	cp /etc/infinito/xwiki.properties /usr/local/xwiki/data/xwiki.properties
fi

exec docker-entrypoint.sh "$@"
