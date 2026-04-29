# Role Image Configuration 🐳

This document is the SPOT for how Docker images are declared, read, overridden,
discovered, and mirrored. For the mirroring pipeline, see [mirror.md](mirror.md).

## Declaration Formats 📋

A role MAY declare images in two ways depending on how the image is used.

### Compose Service Format — `meta/services.yml`

Used for images that are started as part of the role's Docker Compose stack.
The file root IS the services map keyed by `<service-name>` (no `compose:` and
no `services:` wrapper, per [req-008](../../../requirements/008-role-meta-layout.md)):

```yaml
# roles/<role>/meta/services.yml
<service-name>:
  image: <image-name>   # e.g. nextcloud, quay.io/keycloak/keycloak
  version: <tag>        # e.g. latest, 31.0.0
  ports:
    inter: 8080         # internal container port (per req-009)
  # … other compose fields
```

### Flat Image Format — `defaults/main.yml`

Used for images referenced directly in Ansible tasks or templates rather than
through Compose (e.g. images pulled and run ad-hoc by a task). The role name is
implicit from the file path `roles/<role>/defaults/main.yml`.

```yaml
# roles/<role>/defaults/main.yml
images:
  <service-name>:
    image: <image-name>   # e.g. mcr.microsoft.com/playwright, postgres
    version: <tag>        # e.g. v1.58.2-noble
```

- `image` MUST be the image name as it appears in a `docker pull` command,
  without the tag.
- `version` MUST be the tag.
- Images without an explicit registry prefix are treated as Docker Hub images.
- Role-local image defaults MUST stay in `images`. Inventory-side overrides
  MUST NOT be written there.

#### Why `defaults/` and not `vars/`? 🤔

The `images:` block holds role-local defaults, not inventory state. Keeping it
in `defaults/main.yml` makes that intent explicit and keeps the role-side
declaration separate from inventory-side `images_overrides`. Using `vars/` would
give those defaults higher precedence and blur the separation.

## Read 📖

Roles MUST use `lookup('image', ...)` instead of direct `images[...]` access.
The lookup MAY infer the current role id from `role_name`. If `role_name` is not
available, the role id MUST be passed explicitly.

Supported forms:

```yaml
{{ lookup('image', 'playwright', 'image') }}
{{ lookup('image', 'test-e2e-playwright', 'playwright', 'image') }}
{{ lookup('image', 'sys-ctl-hlth-csp', 'csp-checker', 'ref') }}
```

Supported `want` values:

| Value | Returns |
|---|---|
| `all` (default) | the merged mapping |
| `image` | the repository/image name |
| `version` | the tag |
| `ref` | `image:version` |

## Override ✏️

Inventory-side mirror and manual overrides MUST be written to
`images_overrides.<role>.<service>.{image,version}`. `lookup('image', ...)` MUST
prefer `images_overrides` and fall back field-wise to role-local `images`.
Inventory generation MUST keep `images_overrides` separate from `images` so role
defaults remain readable and stable.

Example host-vars override:

```yaml
images_overrides:
  test-e2e-playwright:
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

`utils/docker/image/discovery.py` scans all roles and yields `ImageRef` objects:

| Source file | Key path | Used for |
|---|---|---|
| `meta/services.yml` | `<svc>.image` + `.version` (file root IS the services map) | Compose-managed services |
| `defaults/main.yml` | `images.<svc>.image` + `.version` | Ad-hoc task images |

An `ImageRef` carries: `role`, `service`, `name` (without registry), `version`,
`source` (full pull ref), `registry`, and `source_file`.

## Mirror Integration 🪞

After discovery, images are mirrored to GHCR and the mirror URLs are injected
back into host variables by the inventory creator.

- `meta/services.yml` declarations are resolved back through
  `mirrors.yml.applications.<role>.services.<service>`
- `defaults/main.yml` declarations are resolved back through
  `mirrors.yml.images.<role>.<service>` and land in host vars under
  `images_overrides.<role>.<service>`

See [mirror.md](mirror.md) for the full flow.
