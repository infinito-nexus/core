# Docker Registry Cache

## Description

Cluster-local Docker Hub pull-through cache. Worker nodes pull base images via
this mirror instead of going to `registry-1.docker.io` for every node,
eliminating duplicate network transfers and avoiding Docker Hub rate limits.
On its own host it also caches every other registry a role image names
(ghcr.io, quay.io, mcr.microsoft.com and the rest), one cache per vendor.

## Overview

The role deploys a single `registry:3` instance in pull-through proxy mode on its inventory
group's host. Because the group typically holds exactly one host (the swarm
manager), `DEPLOYMENT_MODE` resolves to `compose` for the role; multi-host
fan-out for the cache itself is out of scope for v1.

Any host that should consume the cache joins the role's group as well. The
shared daemon.json template then emits a `registry-mirrors` block pointing at
`http://<cache-host>:<cache-port>` plus an `insecure-registries` entry so
plain-HTTP communication with the cache is permitted.

## Vendor Registries

Docker's `registry-mirrors` covers Docker Hub only, so the other registries are
cached by rewriting the image reference instead:

- The vendor list is derived from every role image (`image_registries()` in
  [registries.py](../../utils/env/handlers/infinito/cache/registries.py)), so
  a role that adopts an image from a new registry brings its cache with it.
- One more `registry:3` runs per vendor, proxying `https://<vendor>` into its
  own volume. A compromised vendor cache therefore cannot touch the Docker Hub
  cache or another vendor's content.
- One nginx front serves all of them over TLS on the role network's gateway
  address, `<gateway>:5002`, routing `/v2/<vendor>/...` to that vendor's cache.
  It admits `GET` and `HEAD` only and answers every other method with `405`.
  The gateway is neither loopback (Docker skips TLS verification there) nor a
  public address.
- Its certificate is self-signed for that endpoint and trusted in
  `/etc/docker/certs.d/<gateway>:5002/` only, so the anchor vouches for
  nothing else.
- On the cache host in compose mode the image lookup prefixes every vendor
  image with the front, for example `192.168.205.1:5002/ghcr.io/foo/bar:1.0`.
  Docker Hub images keep their plain reference and the mirror.

Vendor pulls on the cache host then depend on this role being up: with the
front or a vendor cache down, the pull fails. Docker Hub pulls keep Docker's
own fallback to `registry-1.docker.io` when the mirror is unreachable. Swarm
deploys keep the swarm registry prefix and are not routed. With no vendor
listed the role renders exactly what it rendered before the vendors existed.

## Features

- Transparent Docker Hub mirror via `registry:3`'s built-in proxy mode.
- One pull-through cache per vendor registry behind a read-only TLS front.
- Idempotent: subsequent role runs reuse the populated cache volume.
- Zero per-image configuration: any image normally pulled from Docker Hub is
  cached on first access and served from local disk afterwards.
- First pull of any image: cache miss, fetched upstream, persisted to disk.
- Subsequent pulls of the same image from any node: served from local cache
  over LAN. On a 3-node cluster pulling identical base images this is the
  difference between three full Hub downloads and one Hub download plus two
  LAN copies.
