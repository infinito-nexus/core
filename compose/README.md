# Compose Configuration 🧩

This directory holds the static configuration assets consumed by the
top-level [compose.yml](../compose.yml) of the local development and CI
testing stack.

## Scope 📋

- The directory MUST contain only files that are bind-mounted into a
  service defined in `compose.yml`.
- The directory MUST NOT host application configuration that belongs to
  an Ansible role. Per-role compose payloads live under
  `roles/<role>/templates/`.
- The directory MUST NOT host workflow scripts, test fixtures, or
  build helpers. Those belong under `scripts/` or `tests/`.

## Layout 🗂️

Each compose service that needs static configuration owns a
sub-directory whose name matches the service. New service-specific
config MUST go into the matching sub-directory rather than at the
`compose/` root.

For the rules that govern `compose.yml` itself (env-variable contract,
profile gating, resource caps), see
[compose.yml.md](../docs/contributing/artefact/files/compose.yml.md).
