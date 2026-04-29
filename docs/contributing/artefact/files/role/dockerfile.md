# `Dockerfile` 🐳

This page is the SPOT for role-local Dockerfiles.
Use this page for placement rules, variable handling, and build wiring.
For the agent-side review workflow during development, see [Development](../../../../agents/action/develop.md).

## Placement 📁

- You MUST place role-local Dockerfiles at `files/Dockerfile`.
- You MUST NOT use `templates/Dockerfile.j2` unless the Dockerfile requires Jinja2
  control-flow logic (e.g. `{% if %}`, `{% for %}`).
- `sys-svc-compose` discovers the Dockerfile automatically by checking
  `templates/Dockerfile.j2` first and then `files/Dockerfile`.
  Both are rendered through the Ansible `template` module.

## Variables ⚙️

- You MUST NOT hard-code values that come from `meta/services.yml` or `vars/main.yml`
  directly in `files/Dockerfile`.
- You MUST declare each external value as a Docker `ARG` without a default value
  so the build always requires the value to be passed explicitly.
- You MUST pass every `ARG` via the `args:` block in `templates/compose.yml.j2`,
  directly after the `{{ lookup('template', 'roles/sys-svc-container/templates/build.yml.j2') }}` call.
- The `vars/main.yml` of the role MUST define the variables referenced in `args:`
  by reading them from `meta/services.yml` through the `lookup('config', ...)` filter.
  This keeps `meta/services.yml` as the single source of truth.

Example `files/Dockerfile`:

```dockerfile
ARG APP_IMAGE
ARG APP_VERSION
FROM ${APP_IMAGE}:${APP_VERSION}
```

Example `templates/compose.yml.j2` wiring:

```yaml
    {{ lookup('template', 'roles/sys-svc-container/templates/build.yml.j2') | indent(4) }}
      args:
        APP_IMAGE:   "{{ APP_IMAGE }}"
        APP_VERSION: "{{ APP_VERSION }}"
```

Example `meta/services.yml` entry (file root IS the services map):

```yaml
myapp:
  image:   myapp/myapp
  version: "1.0"
```

Example `vars/main.yml` entry:

```yaml
APP_IMAGE:   "{{ lookup('config', application_id, 'services.myapp.image') }}"
APP_VERSION: "{{ lookup('config', application_id, 'services.myapp.version') }}"
```

## Image Declaration 🐳

Every Docker image used in a role must be declared in exactly one place — no hardcoded
image strings anywhere else (tasks, templates, defaults).

### Application roles (have `application_id`) 📦

Declare the image at the file root of `meta/services.yml` → `<service>.{image,version}`:

```yaml
# roles/<role>/meta/services.yml  (file root IS the services map)
myapp:
  image:   ghcr.io/vendor/myapp
  version: "1.0"
```

Any Ansible variable that references the image MUST read from config via `lookup('config', ...)`:

```yaml
# vars/main.yml
MY_APP_IMAGE:   "{{ lookup('config', application_id, 'services.myapp.image') }}"
MY_APP_VERSION: "{{ lookup('config', application_id, 'services.myapp.version') }}"
```

### Non-application roles 🔧

For roles without `application_id` that need extra mirrored images (e.g. test runners,
health checkers), use [origin.md](../../image/origin.md) as the SPOT for declaration and access.
Those images MUST be declared under `defaults/main.yml` and MUST be consumed via
`lookup('image', ...)` instead of direct `images[...]` access.

### Image Discovery SPOT 🔍

[image_discovery.py](../../../../../utils/docker/image/discovery.py) is
the single SPOT that enumerates all role images from both sources above.
It is used by the mirror pipeline (`cli/mirror/`) and the external version-check test
([`tests/external/docker/test_image_versions.py`](../../../../../tests/external/docker/test_image_versions.py)).

## When `Dockerfile.j2` Is Acceptable 🤔

A `templates/Dockerfile.j2` is acceptable when the file contains Jinja2
control-flow logic that cannot be expressed through Docker `ARG` alone — for
example, a conditional build step that installs an optional component only when
a feature flag is enabled.

Even in that case, you SHOULD minimize the templated surface: use `{{ variables }}`
only where necessary and keep the static parts of the Dockerfile readable without
rendering it.

## Lint 🔍

The repository lint suite checks for `templates/Dockerfile.j2` files automatically:

- A `Dockerfile.j2` with **no Jinja2 control-flow logic** causes a **test failure**.
  It MUST be migrated to `files/Dockerfile` with `ARG` declarations.
- A `Dockerfile.j2` with **Jinja2 control-flow logic** emits a **warning only**.
  The warning signals that the file should be reviewed to see whether the logic
  can be eliminated and the file migrated.

See [test\_templates.py](../../../../../tests/lint/docker/dockerfile/test_templates.py)
for the implementation.
