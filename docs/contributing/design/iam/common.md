# Common 🧭

This page covers IAM rules that span both providers.
Provider-specific guidance lives in [oidc.md](oidc.md) and [ldap.md](ldap.md).

## Two Providers, Two Namespaces 🎯

| Provider | Role | Variable namespace | Definition file |
|---|---|---|---|
| OIDC | [web-app-keycloak](../../../../roles/web-app-keycloak/) | `OIDC.*` | [11_oidc.yml](../../../../group_vars/all/11_oidc.yml) |
| LDAP | [svc-db-openldap](../../../../roles/svc-db-openldap/) | `LDAP.*` | [12_ldap.yml](../../../../group_vars/all/12_ldap.yml) |

Application roles MUST consume identity data exclusively through these namespaces.
Hardcoding a claim name, attribute name, DN, or endpoint in a role template is forbidden because it bypasses the canonical definition file and breaks platform-wide renames or realm migrations.

## Paired Identifier Principle 🔗

`OIDC.ATTRIBUTES.USERNAME` and `LDAP.USER.ATTRIBUTES.ID` are paired on purpose.
They MUST resolve to the same logical user on both sides so that an account created in OpenLDAP can sign in through Keycloak without an extra mapping step.
Changing one without the other breaks LDAP-OIDC correlation.

## Integration Checklist For New Apps ✅

When you add OIDC or LDAP support to a role, you MUST:

1. Read endpoints, client identifiers, and claim names from `OIDC.*`. Never
   hardcode realm names, URLs, or claim strings.
2. Read attribute names, DNs, and the server URI from `LDAP.*`. Never
   hardcode `uid`, `cn`, base DNs, or LDAP URIs.
3. Use `OIDC.ATTRIBUTES.USERNAME` and `LDAP.USER.ATTRIBUTES.ID` as the user
   identifier on both sides.
4. Keep app-specific Keycloak protocol mappers in a per-client scope file
   under the Keycloak
   [scopes](../../../../roles/web-app-keycloak/templates/import/scopes/)
   directory. Do not extend
   [default.json.j2](../../../../roles/web-app-keycloak/templates/import/clients/default.json.j2).
5. Hide or disable application UI fields that are sourced from OIDC or LDAP,
   per the rules in
   [javascript.js.md](../../artefact/files/role/javascript.js.md).
6. Document the integration in the role README under Features and, when the
   wiring is non-obvious, in the role Developer Notes section. See
   [readme_md.md](../../artefact/files/role/readme_md.md).

## Related Areas 📚

For the broader service-loading model see [base.md](../role/services/base.md).
For the documentation conventions used in this directory see [documentation.md](../../documentation.md).
