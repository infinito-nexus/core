# Todo

- Re-enable LDAP authentication. The `jonmbake/discourse-ldap-auth` plugin currently cloned in `templates/config.yml.j2` does not register `SiteSetting.ldap_auth_enabled` on recent Discourse, so the bootstrap aborts at the first `rails r` call (CI run 25567639207 / job 75058359158). To unblock LDAP again:
  1. Pick a maintained Discourse LDAP plugin (or wrap LDAP behind an OAuth2 façade compatible with Discourse's built-in OIDC plugin).
  2. Swap the plugin URL in `templates/config.yml.j2`.
  3. Flip `services.ldap.{enabled,shared}` in `meta/services.yml` back from literal `false` to the dynamic `'svc-db-openldap' in group_names` form.
  4. Re-add the `ldap` polarity entries (true / false) to both variants in `meta/variants.yml`.
  5. Drop the `# nocheck: dynamic-flag` line above the `ldap:` block.
- Check if this current network setting makes sense. Seems a bit unneccessary complicated. Could be that a more straight foreword approach makes more sense.
- Implement, that username can just be identical to ldap\keycloak username. First dirty hack; Block the changing of the field via JS
