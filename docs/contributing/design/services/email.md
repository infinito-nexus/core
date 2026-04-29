# Email Lookup Plugin 📬

This page documents the contract of the `email` Ansible lookup plugin and the
rules contributors MUST follow when extending it or consuming it from a role.
For administrator-facing configuration (keys, override variables, precedence),
see [email.md](../../../administration/configuration/email.md).

Primary files:
- [email.py](../../../../plugins/lookup/email.py) for the plugin.
- [test_email.py](../../../../tests/unit/plugins/lookup/test_email.py) for unit tests.

## Call Shapes 📞

```yaml
lookup('email')                        # 0 terms: global defaults
lookup('email', '<application_id>')    # 1 term: defaults + per-app overrides
```

Two or more terms MUST fail with `AnsibleError`.

## Resolution Model 🧮

For each short key, the plugin MUST resolve the value from the first defined
source in this order:

1. `applications['<application_id>'].services.email.<key>`, only when
   an `application_id` is passed.
2. A matching `SYSTEM_EMAIL_<KEY>` variable defined anywhere in Ansible
   variable scope (inventory, group vars, host vars).
3. A computed fallback defined in `_compute(short_key, resolved, variables)`.

Per-app overrides MUST be applied after global resolution completes so that
an overridden key wins over both the inventory form and the computed fallback.

## Intra-Key Dependencies 🔗

Computed fallbacks are not independent. `_compute` reads earlier keys from the
in-progress `resolved` dict, so the declaration order in `RESOLUTION_ORDER`
matters:

```
enabled → timeout → external → environment → domain → tls → port → host →
auth → start_tls → smtp → from → username → password
```

Concrete dependencies contributors MUST preserve when changing fallbacks:

- `environment` reads `external`, `TLS_ENABLED`, `DOCKER_IN_CONTAINER`.
- `tls` reads `external` and `TLS_ENABLED`.
- `port` reads `external` and `tls`.
- `host` reads `environment`.
- `auth` reads `environment` and `tls`.
- `from` reads `external` and the `no-reply` user.
- `username` reads `from`.

A new key MUST be placed in `RESOLUTION_ORDER` after every key it depends on,
and the administrator key table MUST be updated to document the new field.

## Helper Lookups 🧰

`_compute` MUST delegate to three other lookup plugins rather than re-reading
project state directly:

- `DomainLookup` resolves the SMTP host when `environment` points to an
  external Mailu deployment. Failures MUST fall back to `localhost`.
- `UsersLookup` yields the `no-reply` user dict used to derive `from` and
  `password`. Missing entries MUST yield an empty dict. The fallback for
  `from` is then `root@<inventory_hostname>.localdomain`.
- `ApplicationsLookup` reads `services.email` for the target
  `application_id`. Unknown applications MUST yield an empty dict.

Each helper MUST forward `roles_dir` when present in `self._kwargs` so tests
can point the lookup at a temporary role tree.

## Templar and Boolean Coercion 🧪

Raw variable values MAY contain Jinja expressions. Any string containing
`{{` MUST be rendered through `self._templar` with `fail_on_undefined=False`.
When no templar is attached (as in some unit tests), the value MUST be
returned as-is so the plugin stays usable from direct Python tests.

`_as_bool` MUST accept the usual string forms (`true|false|yes|no|1|0|on|off`),
booleans, and numbers. Every boolean decision in the fallbacks MUST use it so
that `SYSTEM_EMAIL_*` values coming from YAML, environment variables, or
already-coerced facts all behave the same.

## Consumer Rules 🧷

Role templates and tasks that consume the lookup MUST follow these rules:

- Set the lookup result to a local variable once per section and reference its
  fields, for example:

  ```jinja
  {% set email = lookup('email', application_id) %}
  {% if email.enabled | bool %}
  SMTP_HOST={{ email.host }}
  SMTP_PORT={{ email.port }}
  SMTP_FROM={{ email['from'] }}
  SMTP_USERNAME={{ email.username }}
  SMTP_PASSWORD={{ email.password }}
  {% endif %}
  ```

- `from` is a reserved word in Jinja. It MUST be accessed with bracket notation
  (`email['from']`), not dotted access.
- For `vars/main.yml`, contributors MUST define a single holder variable
  (`<ROLE>_EMAIL: "{{ lookup('email', application_id) }}"`) and reference its
  keys. Re-calling the lookup on every reference would re-run the resolution.
- Non-app consumers (any `sys-*` role) MUST call `lookup('email')` without an
  `application_id` so they never trigger a per-app merge.

## Mailu Dependency Detection 🚨

Roles that call `lookup('email', ...)` are treated as dependents of Mailu. The
integration check
[test_mailu_dependency.py](../../../../tests/integration/services/test_mailu_dependency.py)
scans every role for the `lookup('email'` pattern and fails if such a role
does not declare `services.email` with `enabled: true` and
`shared: true` at the file root of its `meta/services.yml` (per
[req-008](../../../requirements/008-role-meta-layout.md)). A new email
consumer MUST declare that service block in its role's `meta/services.yml`.

## See Also 🔗

- [email.md](../../../administration/configuration/email.md) for the administrator configuration reference.
- [base.md](base.md) for the broader service registration, loading, and injection model.
