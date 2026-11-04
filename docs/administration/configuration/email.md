# Email Configuration 📬

This page documents the administrator-facing surface of outgoing email
configuration. For the plugin contract and extension rules, see
[email.md](../../contributing/design/role/services/email.md).

Infinito.Nexus exposes outgoing email settings through the `email` lookup
plugin. All role templates and tasks read email settings via `lookup('email')`
(global) or `lookup('email', '<application_id>')` (per-app). No global
`SYSTEM_EMAIL_*` variable file ships with the project. Resolution defaults
derive from project-wide inputs: `DOMAIN_PRIMARY`, `TLS_ENABLED`,
`DOCKER_IN_CONTAINER`, the group membership of the mail provider that
[web-app-email](../../../roles/web-app-email/) selects, and the `no-reply` user.

## Mail Provider 📮

Roles depend on `web-app-email`, which stands for the mail server and selects
the provider role that serves it. The default is `web-app-stalwart`. To select
another provider, override the wrapper in the inventory and add that role to
its groups:

```yaml
applications:
  web-app-email:
    services:
      email:
        provider: <provider role id>
```

`MAIL_PROVIDER` is derived from this setting through `lookup('mail_provider')`
and is not set by hand.

### Upgrading an existing inventory ⬆️

Every mail consumer gates on `web-app-email`, so an inventory written before
the wrapper existed, listing only `web-app-stalwart` (or `web-app-mailu`),
would deploy with mail switched off everywhere. Before the next deploy:

1. Add `web-app-email` to the inventory groups, on the same hosts that carry
   the mail provider:

   ```yaml
   all:
     children:
       web-app-email:
         hosts:
           <mail host>:
       web-app-stalwart:
         hosts:
           <mail host>:
   ```

2. Remove a hand-set `MAIL_PROVIDER`; select another provider through the
   `applications.web-app-email.services.email.provider` override instead.

`cli/administration/inventory/validate` rejects an inventory that carries a
mail provider without `web-app-email` on the same hosts, and one that sets
`MAIL_PROVIDER` by hand.

## Resolved Keys 🔑

Every call returns a flat dict with the following keys. Each key MAY be
overridden from inventory by setting the matching `SYSTEM_EMAIL_<KEY>` variable
(uppercase, with the `SYSTEM_EMAIL_` prefix).

| Key | Override Variable | Default | Meaning |
|---|---|---|---|
| `enabled` | `SYSTEM_EMAIL_ENABLED` | `true` | Whether outgoing mail is enabled. |
| `timeout` | `SYSTEM_EMAIL_TIMEOUT` | `"30"` | SMTP/client timeout in seconds. |
| `external` | `SYSTEM_EMAIL_EXTERNAL` | `true` if the selected mail provider's group has a host, else `false` | True when the selected mail provider is reachable (otherwise local delivery). |
| `environment` | `SYSTEM_EMAIL_ENVIRONMENT` | `external` if `external` or `TLS_ENABLED`, else `localhost`, plus `_container` suffix if `DOCKER_IN_CONTAINER` and `TLS_ENABLED` is false | One of `external`, `external_container`, `localhost`, `localhost_container`. |
| `domain` | `SYSTEM_EMAIL_DOMAIN` | `DOMAIN_PRIMARY` | Primary mail domain. |
| `tls` | `SYSTEM_EMAIL_TLS` | `false` if not `external`, else `TLS_ENABLED` | True when SMTPS SHOULD be used. |
| `port` | `SYSTEM_EMAIL_PORT` | `465` when `external` and `tls`, else `25` | SMTP port. |
| `host` | `SYSTEM_EMAIL_HOST` | `localhost` for `external_container`, `localhost`, `localhost_container`, else the selected mail provider's domain | SMTP host. |
| `auth` | `SYSTEM_EMAIL_AUTH` | `false` for `external_container` and `localhost`, else equal to `tls` | Whether SMTP auth is required. |
| `start_tls` | `SYSTEM_EMAIL_START_TLS` | `false` | Whether STARTTLS is used. |
| `smtp` | `SYSTEM_EMAIL_SMTP` | `true` | Whether SMTP delivery is enabled. |
| `from` | `SYSTEM_EMAIL_FROM` | email of the `no-reply` user when `external`, else `root@<inventory_hostname>.localdomain` | Envelope/from address. |
| `username` | `SYSTEM_EMAIL_USERNAME` | equal to `from` | SMTP username. |
| `password` | `SYSTEM_EMAIL_PASSWORD` | `no-reply` user's token for the selected mail provider, else empty string | SMTP password. |

## Per-Application Overrides 🧩

Applications MAY override any subset of these keys under
`services.email` in their role or inventory.

Role defaults:

```yaml
# roles/<application_id>/meta/services.yml
email:
  host: smtp.app.example.org
  port: 587
  tls: true
```

Inventory overrides:

```yaml
# group_vars/<group>.yml or host_vars/<host>.yml
applications:
  web-app-nextcloud:
    services:
      email:
        username: nextcloud@example.org
```

Overrides are merged on top of the resolved defaults. Keys MUST use the short,
lowercased names listed above.

## Precedence 📊

For each key, the first defined source wins:

1. `applications['<application_id>'].services.email.<key>`, applied
   only when an `application_id` is passed.
2. A `SYSTEM_EMAIL_<KEY>` variable defined in inventory, group vars, or host
   vars. No such file ships with the project. This form is an escape hatch for
   site-specific overrides.
3. The plugin's built-in fallback computed from `DOMAIN_PRIMARY`, the
   selected mail provider's group, the `no-reply` user, and related inputs.

## See Also 🔗

- [email.md](../../contributing/design/role/services/email.md) for the plugin contract and extension rules.
