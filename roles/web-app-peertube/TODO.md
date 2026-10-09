# Todos

- [DKIM activate](https://docs.joinpeertube.org/install/docker)
- The plugin needs to be manually activated in the admin interface. would be nice if this is automatized as well
- `tasks/oidc/disable.yml` runs `npm run plugin:uninstall` through `shell` with `ignore_errors: true` on every deploy without `sso`, so the task reports `changed` on every role sync although nothing is installed; options: probe `/data/plugins/node_modules/peertube-plugin-auth-openid-connect` first (as `oidc/enable.yml` does) and set `changed_when` from the probe.
- `tasks/02_fix-application-schema.yml` "Back-fill column defaults" reports `changed` and notifies `compose-up` on every role sync, also when the defaults are already in place; options: let the SQL return the columns it altered and derive `changed_when` from the returned rows.
