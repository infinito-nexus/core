# Image Mirroring 🪞

This document explains why image mirroring exists, how it works, and what each component does. For how images are declared in roles, see [origin.md](origin.md).

## Why Mirrors Exist 🎯

Upstream registries (Docker Hub, quay.io, mcr.microsoft.com, ghcr.io) impose **rate limits** and occasionally have **availability issues**. CI on GitHub-hosted runners also sees **IP-range- and geo-dependent failures**, plus transient `403`, `429`, and `5xx` responses when many jobs pull the same image directly from upstream. This is especially visible with Playwright images sourced from `mcr.microsoft.com`.

To solve this, CI mirrors all upstream images used in the project to GHCR (`ghcr.io`) under the project namespace before deploy tests run. Deploy jobs then pull from the GHCR mirror instead of the upstream registry, so a temporary upstream rate limit, outage, or geo-block does not fail an otherwise healthy change.

This also enables **fork PRs** to pull images without needing upstream credentials, because the mirror is public.

## Naming Convention 📛

Mirrored images follow this scheme:

```
ghcr.io/{namespace}/{repository}/mirror/{registry}/{name}:{version}
```

| Segment | Example |
|---|---|
| `namespace` | `kevinveenbirkenbach` |
| `repository` | `infinito-nexus-core` |
| `registry` | `docker.io`, `quay.io`, `mcr.microsoft.com`, `ghcr.io` |
| `name` | `nextcloud`, `keycloak/keycloak`, `prom/prometheus` |
| `version` | `latest`, `31.0.0` |

Example: `ghcr.io/kevinveenbirkenbach/infinito-nexus-core/mirror/docker.io/nextcloud:production-fpm-alpine`

## Components 🧩

### Image Discovery 🔍

`utils/docker/image/discovery.py` discovers all role images via `iter_role_images()`. See [origin.md](origin.md) for the declaration format and supported registries.

### GHCRProvider 🐳

`cli/mirror/providers.py` contains the `GHCRProvider` class, which computes the destination image name via `image_base(img)` and provides `add_args` / `from_args` so all CLI tools share a single argument definition (SPOT).

### Resolver 🗺️

`cli/mirror/resolver/__main__.py` reads all role images and outputs a `mirrors.yml` file with separate sections for compose images and role-local flat images:

```yaml
applications:
  <role>:
    services:
      <service>:
        image: ghcr.io/{namespace}/{repository}/mirror/{registry}/{name}
        version: <tag>
images:
  <role>:
    <service>:
      image: ghcr.io/{namespace}/{repository}/mirror/{registry}/{name}
      version: <tag>
```

The split matches the source declaration:

- `meta/services.yml` image refs stay on the existing `applications.*.services.*` path
- `defaults/main.yml` image refs are emitted under `images.*.*`

This file is consumed by the inventory creator to substitute mirror URLs into host variables.

### Sync 🔄

`cli/mirror/sync/__main__.py` copies each image from the upstream source to the GHCR mirror destination using `skopeo copy`. Supports `--only-missing` to skip already-mirrored images and `--images-per-hour` for throttling.

### Wait Script ⏳

`scripts/meta/wait/mirrors.sh` waits for fork PRs until all required mirror images are available in GHCR before letting the deploy tests proceed. This is necessary because fork PRs cannot push images themselves; the `pull_request_target` event handles that.

## CI Integration 🔄

The mirror workflow runs as stage 8 of the CI pipeline. See [ci.md](../git/pipeline.md). It runs in parallel with the DNS tests and MUST complete before deploy tests start.

### CI Flow 📋

1. Image discovery scans role declarations in `meta/services.yml` and `defaults/main.yml`.
2. [images-mirror-missing.yml](../../../../.github/workflows/images-mirror-missing.yml) copies only missing upstream refs into GHCR via `cli.mirror.sync --only-missing`. Optional Docker Hub credentials reduce source-side rate limits during that sync.
3. Fork PRs cannot publish packages themselves, so their untrusted `pull_request` runs wait in `scripts/meta/wait/mirrors.sh` until a trusted producer run has published the required refs.
4. Inventory generation writes the resulting mirror refs from `mirrors.yml` back into host vars.
5. Deploy and test jobs resolve images from `ghcr.io/{namespace}/{repository}/mirror/...` instead of pulling directly from Docker Hub, MCR, or other upstream registries.

The mirrors file is generated into the inventory directory. The inventory creator applies mirror image overrides to host variables via `cli/create/inventory/mirror_overrides.py`, which reads both top-level keys from `mirrors.yml` and writes into host vars as follows:

- `applications.{role}.services.{service}.image`: Populated from `mirrors.yml.applications` and still subject to `mirror_policy`.
- `images_overrides.{role}.{service}.image`: Populated from `mirrors.yml.images` and consumed by `lookup('image', ...)`.

### Mirror Policy 📋

Each service in host vars MAY carry a `mirror_policy` field that controls how the override is applied:

| Policy | Behavior |
|---|---|
| `if_missing` (default) | Fill `image`/`version` only if they are blank or absent |
| `force` | Always overwrite `image`/`version` from the mirror |
| `skip` | Never touch this service |

## Adding a New Mirrored Image 🆕

No manual registration is needed. Images declared in a role are automatically discovered and included in the next mirror run. See [origin.md](origin.md) for the correct declaration format.

For CI-critical images, you SHOULD pin an exact upstream tag instead of using mutable tags such as `latest`. This is especially important for Playwright images mirrored from `mcr.microsoft.com`, where exact tags avoid CDN propagation races and make flaky upstream releases easier to diagnose.

## Cleanup 🗑️

To delete stale private GHCR mirror packages (e.g. packages pushed before `GITHUB_TOKEN` authentication was adopted), see [cleanup.md](../../tools/ghcr/cleanup.md).
