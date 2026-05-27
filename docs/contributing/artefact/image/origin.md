# Role Image Configuration 🐳

This page describes how Docker images are declared, read, overridden, discovered, and mirrored.
For the mirroring pipeline, see [mirror.md](mirror.md).

## Declaration Format 📋

Every role MUST declare its Docker images in `meta/services.yml`.
The file root IS the services map keyed by `<service-name>` (no `compose:` and no `services:` wrapper):

```yaml
# roles/<role>/meta/services.yml
<service-name>:
  image: <image-name>   # e.g. nextcloud, quay.io/keycloak/keycloak, mcr.microsoft.com/playwright
  version: <tag>        # e.g. latest, 31.0.0, v1.58.2-noble
  ports:
    internal:
      http: 8080        # internal container port (category-keyed; see layout.md)
  # … other compose fields
```

- `image` MUST be the image name as it appears in a `docker pull` command, without the tag.
- `version` MUST be the tag.
- Images without an explicit registry prefix are treated as Docker Hub images.
- Compose-managed services and ad-hoc task images both live under the same key on the role's primary or auxiliary service entries.
- Role-local image defaults MUST stay in `meta/services.yml`.
- Inventory-side overrides MUST NOT be written there.

## Read 📖

Roles MUST use `lookup('config', '<role_id>', 'services.<service_name>.<field>')` to read image declarations.
That path goes through the merged `applications` map, so it transparently picks up the mirror overrides written by the inventory creator (see [mirror.md](mirror.md)).

Pattern:

```yaml
{{ lookup('config', '<role_id>', 'services.<service_name>.image') }}:{{ lookup('config', '<role_id>', 'services.<service_name>.version') }}
```

Examples:

```yaml
{{ lookup('config', 'test-e2e-playwright', 'services.playwright.image') }}
{{ lookup('config', 'sys-ctl-hlth-csp', 'services.csp-checker.image') }}:{{ lookup('config', 'sys-ctl-hlth-csp', 'services.csp-checker.version') }}
```

## Override ✏️

The override path is host-vars `applications.<role>.services.<service>.{image,version}`.
The inventory mirror step (see [mirror.md](mirror.md)) writes there automatically; manual overrides go to the same key.

```yaml
applications:
  test-e2e-playwright:
    services:
      playwright:
        image: ghcr.io/example/mirror/mcr.microsoft.com/playwright
        version: v1.58.2-noble
```

## Supported Registries 🌐

The following registries are discovered and mirrored:

| Registry | Example image |
|---|---|
| `docker.io` (Docker Hub) | `postgres`, `nextcloud`, `prom/prometheus` |
| `quay.io` | `quay.io/keycloak/keycloak` |
| `ghcr.io` | `ghcr.io/mastodon/mastodon` |
| `mcr.microsoft.com` | `mcr.microsoft.com/playwright` |

Images from other registries are ignored by the discovery and mirroring tooling.

## Discovery 🔍

`utils/docker/image/discovery.py` scans every `roles/<role>/meta/services.yml` and yields `ImageRef` objects for each top-level service entry that carries both `image` and `version`.

An `ImageRef` carries: `role`, `service`, `name` (without registry), `version`, `source` (full pull ref), `registry`, and `source_file`.

## Mirror Integration 🪞

After discovery, images are mirrored to GHCR and the mirror URLs are injected back into host variables by the inventory creator.
Declarations are resolved back through `mirrors.yml.applications.<role>.services.<service>` and land in host vars at the same path.

See [mirror.md](mirror.md) for the full flow.
