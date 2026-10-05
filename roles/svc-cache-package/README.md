# Package cache

## Description

[Nexus Repository](https://www.sonatype.com/products/sonatype-nexus-repository) is a repository manager that proxies package registries and serves an artefact it has already fetched from local disk. [nginx](https://nginx.org/) sits in front of it and answers for the upstream hostnames themselves, so a package manager keeps the URLs it was built with and still reads through the proxy.

## Overview

The role deploys two containers on its inventory group's host: the repository manager and its nginx frontend. Both run in compose mode on the manager, like the sibling [svc-registry-cache](../svc-registry-cache/README.md).

[upstreams.conf.j2](./templates/upstreams.conf.j2) is rendered to the host and mounted into the frontend as `conf.d/upstreams.conf`. Its content comes from the `cache:` sections of the roles' `meta/networks.yml`, so no hostname, repository or upstream URL is written in this role.

`compose.cache-consumer.yml.j2`, `apt.list.j2`, `npmrc.j2` and `pip.conf.j2` under `templates/`, and the shell scripts under `files/`, belong to the development compose stack, which drives them through [render.py](../../utils/cache/render.py) and [compose.py](../../cli/administration/deploy/development/compose.py). The Ansible deployment reads none of them.

## Features

- **Declaration driven:** Every proxied repository and every answered hostname comes from the `cache:` declarations, collected by the `cache_upstreams` and `cache_repos` lookups. A new upstream is added by declaring it there.
- **Mirror failover:** A repository that declares a mirror is served through a guarded location: a 5xx from its primary remote re-runs the same path against the sibling repository, while a 404 is passed straight back.
- **Persistent store:** Proxied artefacts live in a named volume, so a redeploy reuses what earlier runs already pulled.
- **Backup free:** The volume is backup-disabled and its backup consumer stays off; every artefact in it is re-fetchable from its upstream.
