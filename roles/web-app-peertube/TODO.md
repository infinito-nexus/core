# Todos

- [DKIM activate](https://docs.joinpeertube.org/install/docker)
- `tasks/02_fix-application-schema.yml` "Back-fill column defaults" reports `changed` and notifies `compose-up` on every role sync, also when the defaults are already in place; options: let the SQL return the columns it altered and derive `changed_when` from the returned rows.
