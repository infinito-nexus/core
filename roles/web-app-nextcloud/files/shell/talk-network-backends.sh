#!/bin/sh
# Param: TALK_NETWORK_BACKEND_URLS comma-separated backend base URLs of the network siblings beyond NC_DOMAIN
# The aio-talk start script rewrites signaling.conf with one backend (https://$NC_DOMAIN) on every start,
# while Talk reports the backend URL of each request's network, so the other siblings are appended here.
set -eu
conf=/conf/signaling.conf
names=backend-1
index=1
IFS=,
for url in ${TALK_NETWORK_BACKEND_URLS:-}; do
	index=$((index + 1))
	printf '\n[backend-%s]\nurl = %s\nsecret = %s\n' "$index" "$url" "$SIGNALING_SECRET" >>"$conf"
	names="$names, backend-$index"
done
sed -i "s/^backends = backend-1\$/backends = ${names}/" "$conf"
exec "$@"
