# Todos

- [DKIM activate](https://docs.joinpeertube.org/install/docker)
- `tasks/02_fix-application-schema.yml` "Back-fill column defaults" reports `changed` and notifies `compose-up` on every role sync, also when the defaults are already in place; options: let the SQL return the columns it altered and derive `changed_when` from the returned rows.
- The plugin needs to be manually activated in the admin interface. would be nice if this is automatized as well
- Run `npm run regenerate-thumbnails` when an upgrade crosses v8.1.0, which upstream recommends after `peertube-8.1.js`
