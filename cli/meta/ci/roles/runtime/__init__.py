"""Summarise Ansible `profile_roles` runtimes per matrix-deploy variant.

Single responsibility per module:

- `model`    — the `RoleRuntime` record (one role's time within a segment).
- `logparse` — Ansible run log -> records (splits by matrix round/pass markers).
- `csvio`    — records <-> CSV (the on-disk metrics schema, a single SPOT).
- `render`   — records -> text in the format chosen via `--format`.
- `github`   — a run/job URL -> records (downloads the CSV artifacts via `gh`).
- `sources`  — pick the right loader for a log path, CSV path, or URL.

CLI: `python -m cli.meta.ci.roles.runtime <source> [--format ...] [--output ...]`.
"""
