# Compose Configuration 🧩

This directory holds the static configuration assets consumed by the
top-level [compose.yml](../compose.yml) of the local development and CI
testing stack.

## Scope 📋

- The directory MUST contain only files that are bind-mounted into a
  service defined in `compose.yml`, or that form the build context of
  one, such as [target/](target/README.md), and the stack declaration
  [stacks.yml](stacks.yml), which names every local stack, its lifecycle
  class and the make targets that start it;
  `python -m cli.meta.stacks <target>` prints the stacks a target starts.
- The directory MUST NOT host application configuration that belongs to
  an Ansible role. Per-role compose payloads live under
  `roles/<role>/templates/`.
- The directory MUST NOT host workflow scripts or test fixtures, nor
  build helpers outside a service's build context. Those belong under
  `scripts/` or `tests/`.

## Layout 🗂️

Each compose service that needs static configuration owns a
sub-directory whose name matches the service. New service-specific
config MUST go into the matching sub-directory rather than at the
`compose/` root.

For the rules that govern `compose.yml` itself (env-variable contract,
profile gating, resource caps), see
[compose.yml.md](../docs/contributing/artefact/files/compose.yml.md).
