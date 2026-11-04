# Todos

- [DKIM activate](https://docs.joinpeertube.org/install/docker)
- `tasks/02_fix-application-schema.yml` "Back-fill column defaults" reports `changed` and notifies `compose-up` on every role sync, also when the defaults are already in place; options: let the SQL return the columns it altered and derive `changed_when` from the returned rows.
- The plugin needs to be manually activated in the admin interface. would be nice if this is automatized as well
- Run `npm run regenerate-thumbnails` when an upgrade crosses v8.1.0, which upstream recommends after `peertube-8.1.js`
- A role group change reaches PeerTube only through `files/sql/rbac/reconcile-roles.sql` at a deploy or on the `sys-ctl-mtn-rbac-sync` timer (so the moderator mapping has no Playwright scenario, a spec can trigger neither), and display name and language only at account creation, because `peertube-plugin-auth-openid-connect` passes no `userUpdater` and its `role-property` expects an integer claim; options: a Keycloak user-attribute mapper reading an integer group attribute on `/roles/web-app-peertube/*`, or an upstream `userUpdater` in the plugin.
- `language-property` reading the `locale` claim has no Playwright scenario, because the plugin applies it only when it creates the account and the biber persona's account exists before the spec runs; options: a spec that deletes biber's PeerTube account, sets the Keycloak `locale` attribute and signs in again, or the upstream `userUpdater` above.
