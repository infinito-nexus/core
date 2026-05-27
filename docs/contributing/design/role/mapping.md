# Role Mapping 🧩

The role-mapping schema decides which files MAY appear inside `roles/<role-name>/`, which MUST appear, and which dotted-path entries inside those files MUST be set per role type.

## Source 📁

[mapping.py](../../../../utils/roles/mapping.py) is the only authoritative location for this schema.
It exposes the path constants, the `ROLE_FILES` dict that scopes each path per role type, and the `mandatory`, `allowed` and `marker` flags that drive both lint enforcement and role-type detection.
Every consumer (lint tests, role-type detection, the CLI documented below) MUST read from this file.
Adding a new role type or a new role file MUST happen here first; the rest of the system reads the dict at runtime.

## Role-Type Detection 🎯

[type.py](../../../../utils/roles/type.py) consumes the same schema.
It walks every entry flagged `marker: True` in `ROLE_FILES` and adds the surrounding type to a role's type set whenever the marker's dotted path resolves to a non-empty value in the role's file.
A role MAY belong to several types simultaneously (an application that also ships a systemd unit declares both `application_id` and `system_service_id`); `get_role_types` returns the full set.

## CLI Inspector 🛠️

[the mapping CLI](../../../../cli/meta/roles/mapping/__main__.py) renders the schema in three views.
Every subcommand accepts `--type <ROLE_TYPE>` to narrow output to a single role type and `--format text|json` to switch between human-readable text (default) and a machine-readable structure.

### Subcommands 📋

| Subcommand | Output |
|---|---|
| `files` | Every role file with its per-type policy and dotted-path entries. |
| `types` | Every role type with the files it MAY or MUST ship. |
| `markers` | The `file.path` pairs that decide each role type. |

### Examples ✍️

List every file with its policy across all types:

```shell
python -m cli.meta.roles.mapping files
```

Narrow to one role type:

```shell
python -m cli.meta.roles.mapping types --type application
```

Get the marker schema as JSON for piping into `jq`:

```shell
python -m cli.meta.roles.mapping markers --format json
```

## Lint Integration 🚦

Two integration tests consume `ROLE_FILES` directly so adding or moving a file in the schema propagates the constraint without further edits:

- [test_mapping.py](../../../../tests/integration/roles/meta/test_mapping.py) iterates every role and every entry in `ROLE_FILES`, then reports forbidden files, missing mandatory files, forbidden entries, and missing mandatory entries in one structured fail report.
- [test_coverage.py](../../../../tests/integration/roles/meta/variants/test_coverage.py) consults `get_role_types` so the variant-coverage requirement only applies to roles that include `ROLE_TYPE_APPLICATION` in their type set.
