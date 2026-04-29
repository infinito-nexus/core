# CoreDNS Sidecar Config 🛰️

Static configuration for the `coredns` service in
[compose.yml](../../compose.yml). The sidecar resolves the dev/CI
stack's internal hostnames so the `infinito` runner can reach its own
applications without hitting an external resolver.

## Scope 📋

- This directory MUST contain only files consumed by the `coredns`
  compose service.
- The `Corefile.tmpl` MUST be the source of truth. It is rendered to
  `Corefile` by [coredns.py](../../cli/deploy/development/coredns.py)
  via `envsubst`, using values from `env.ci` (overridable through the
  CLI's environment).
- The rendered `Corefile` is build artefact and MUST stay in
  `.gitignore`.

## Files 📄

- `Corefile.tmpl` — `envsubst` template processed at stack start.
- `Corefile` — rendered output, bind-mounted read-only into the
  `coredns` container at `/Corefile`.
