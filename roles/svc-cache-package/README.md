# Package cache

## Description

[Nexus Repository](https://www.sonatype.com/products/sonatype-nexus-repository) is a repository manager that proxies package registries and serves an artefact it has already fetched from local disk. [nginx](https://nginx.org/) sits in front of it and answers for the upstream hostnames themselves, so a package manager keeps the URLs it was built with and still reads through the proxy.

## Overview

The role deploys two containers on its inventory group's host: the repository manager and its nginx frontend. Both run in compose mode on the manager, like the sibling [svc-registry-cache](../svc-registry-cache/README.md).

[upstreams.conf.j2](./templates/upstreams.conf.j2) is rendered to the host and mounted into the frontend as `conf.d/upstreams.conf`. Its content comes from the `cache:` sections of the roles' `meta/networks.yml`, so no hostname, repository or upstream URL is written in this role.

The development compose stack renders its runner's cache files from [cache-consumer.yml.jinja](../../compose/templates/cache-consumer.yml.jinja), [npmrc.jinja](../../compose/templates/npmrc.jinja) and [pip.conf.jinja](../../compose/templates/pip.conf.jinja) through [render.py](../../utils/cache/render.py); the Ansible deployment reads none of them. Both run the scripts under `files/shell/`: [certs.sh](./files/shell/certs.sh) issues the frontend CA and one leaf per TLS host through [cert-gen.sh](./files/shell/cert-gen.sh), [bootstrap.sh](./files/shell/bootstrap.sh) creates the declared repositories, and [ca.sh](./files/shell/ca.sh) installs the frontend CA into a trust store. [compose.py](../../cli/administration/deploy/development/compose.py) runs ca.sh in the development runner, and the roles whose images build through the cache stage it into their build context.

## Features

- **Declaration driven:** Every proxied repository and every answered hostname comes from the `cache:` declarations, collected by the `cache_upstreams` and `cache_repos` lookups. A new upstream is added by declaring it there.
- **Mirror failover:** A repository that declares a mirror is served through a guarded location: a 5xx from its primary remote re-runs the same path against the sibling repository, while a 404 is passed straight back.
- **Persistent store:** Proxied artefacts live in a named volume, so a redeploy reuses what earlier runs already pulled.
- **Backup free:** The volume is backup-disabled and its backup consumer stays off; every artefact in it is re-fetchable from its upstream.
- **Self-provisioning:** A `bootstrap` sidecar runs [bootstrap.sh](./files/shell/bootstrap.sh) from inside the stack whenever the cache starts, gated on the repository manager's healthcheck. It re-creates every declared repository on a `/nexus-data` that came back empty. The deploy runs the same script from the host, over `docker exec`, so a deployment converges before its tasks finish.
