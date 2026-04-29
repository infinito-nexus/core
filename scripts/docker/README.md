# Docker Runner Scripts 🐳

Shell helpers that run inside the `infinito` runner container defined by
the top-level [compose.yml](../../compose.yml). They cover container
lifecycle (entry, healthcheck) and integration with peer compose
services (e.g. the `registry-cache` pull-through proxy).

## Scope 📋

- This directory MUST contain only scripts that execute inside the
  `infinito` container, either as the container entrypoint, as a
  Docker `HEALTHCHECK`, or as a `systemd` unit hook.
- This directory MUST NOT host host-side tooling. Scripts that run on
  the developer or CI host belong under their workflow-specific path
  (for example `scripts/tests/`, `scripts/image/`, `scripts/meta/`).
- This directory MUST NOT host application logic that belongs to an
  Ansible role.

## Bind-mounted scripts 🔗

A script that is bind-mounted from this directory into a fixed in-container
path (see [compose.yml](../../compose.yml)) MUST keep its git executable
bit, because Docker bind-mounts preserve host file permissions and the
in-container caller (systemd, dockerd, the entrypoint) cannot recover from
a non-executable mount.

When a new script is added with a bind-mount target, its purpose and
in-container target path SHOULD be documented at the call site (the
matching `compose/<service>/` README, or [compose.yml.md](../../docs/contributing/artefact/files/compose.yml.md)).

## Distro portability 🌐

A script in this directory MUST work across every distro variant that
the runner image is built for (currently Debian, Ubuntu, Arch, Fedora,
CentOS). Tool availability differs across these variants, so a script
SHOULD branch on `command -v <tool>` rather than on distro IDs.
