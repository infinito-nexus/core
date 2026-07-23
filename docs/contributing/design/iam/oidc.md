# OIDC 🪪

This page describes how application roles consume the platform's OIDC provider, [Keycloak](../../../../roles/web-app-keycloak/).
The variable tree lives in [11_oidc.yml](../../../../group_vars/all/11_oidc.yml) under `defaults_oidc`.
For the cross-cutting IAM principles, including the paired identifier rule shared with LDAP, see [common.md](common.md).
For LDAP-side details see [ldap.md](ldap.md).

## Variable Tree 🌳

The `OIDC` tree is a lazy group_var: it resolves in the consuming role's
context, so the issuer family-aligns to that consumer (clearnet page →
clearnet issuer, onion page → onion issuer). Inventory overrides therefore
live under `OIDC_OVERRIDE:` — an inventory-level `OIDC:` block would shadow
the lazy resolution and is rejected by a constructor assert.

The keys consumers care about:

| Key | Meaning |
|---|---|
| `OIDC.URL` | Base URL of the Keycloak instance |
| `OIDC.CLIENT.ID` | Client identifier, defaults to `SOFTWARE_DOMAIN` |
| `OIDC.CLIENT.SECRET` | Client secret, MUST come from the inventory (`OIDC_OVERRIDE.CLIENT.SECRET`) |
| `OIDC.CLIENT.REALM` | Realm the client is registered in |
| `OIDC.CLIENT.ISSUER_URL` | Issuer URL, equal to discovery `issuer` |
| `OIDC.CLIENT.DISCOVERY_DOCUMENT` | `.well-known/openid-configuration` URL |
| `OIDC.CLIENT.AUTHORIZE_URL` | Authorization endpoint |
| `OIDC.CLIENT.TOKEN_URL` | Token endpoint |
| `OIDC.CLIENT.USER_INFO_URL` | Userinfo endpoint |
| `OIDC.CLIENT.LOGOUT_URL` | RP-initiated logout endpoint |
| `OIDC.CLIENT.CERTS` | JWKS endpoint, equal to discovery `jwks_uri` |
| `OIDC.CLIENT.ACCOUNT.URL` | User self-service console root |
| `OIDC.CLIENT.ACCOUNT.PROFILE_URL` | Personal-info section deep link |
| `OIDC.CLIENT.ACCOUNT.SECURITY_URL` | Login and security section deep link |
| `OIDC.CLIENT.CHANGE_CREDENTIALS` | Direct link to the credentials editor |
| `OIDC.CLIENT.RESET_CREDENTIALS` | Public password-reset entry point |
| `OIDC.BUTTON_TEXT` | Default label for SSO login buttons |

When a role needs an OIDC endpoint, it MUST template the corresponding `OIDC.CLIENT.*` value rather than build the URL from `OIDC.URL` itself.
The URL builders in [11_oidc.yml](../../../../group_vars/all/11_oidc.yml) already handle realm and protocol concerns.

## Claim Attributes 🏷️

`OIDC.ATTRIBUTES` lists the claim names that downstream applications read out of the userinfo response and ID token:

| Key | Default value | Meaning |
|---|---|---|
| `OIDC.ATTRIBUTES.USERNAME` | `preferred_username` | Stable user identifier |
| `OIDC.ATTRIBUTES.GIVEN_NAME` | `givenName` | First name |
| `OIDC.ATTRIBUTES.FAMILY_NAME` | `surname` | Last name |
| `OIDC.ATTRIBUTES.EMAIL` | `email` | Email address |

Rules:

- Application roles MUST identify users via `OIDC.ATTRIBUTES.USERNAME`. They
  MUST NOT introduce a private claim name (for example `user_id`, `uid`, or
  `oauth_uid`) when `preferred_username` already satisfies the requirement.
- Roles MUST NOT hardcode the literal value `preferred_username`. Always
  template `{{ OIDC.ATTRIBUTES.USERNAME }}`.
- The standard OIDC `sub` claim is permitted as an alternative when the
  application explicitly requires a UUID-shaped identifier and stores its own
  mapping table. In that case the role MUST document the deviation in its
  README.
- The OIDC username claim is paired with the LDAP login attribute by design.
  See [ldap.md](ldap.md) for the LDAP-side rule.

## Keycloak Client Templates 📦

Keycloak client definitions are imported from
[clients](../../../../roles/web-app-keycloak/templates/import/clients/). The
default template in
[default.json.j2](../../../../roles/web-app-keycloak/templates/import/clients/default.json.j2)
is shared by every application client.

Rules:

- The shared `default.json.j2` MUST stay generic. App-specific protocol
  mappers, claims, or scopes MUST NOT be added there because the change
  affects every other client.
- An app that needs an extra mapper MUST add it through a per-client scope.
  See
  [nextcloud.json.j2](../../../../roles/web-app-keycloak/templates/import/scopes/nextcloud.json.j2)
  for the precedent: a dedicated scope holds the Nextcloud-specific UID and
  quota mappers and is attached only to the Nextcloud client.
- New scope files MUST be referenced from the consuming app via its
  `KEYCLOAK_RBAC_GROUP_CLAIM` style configuration or via the
  `optionalClientScopes` list in the client template.

## Consumer Pattern 🧩

A typical OIDC-consuming role wires the values into its environment template, for example [env.j2](../../../../roles/web-app-mastodon/templates/env.j2):

```jinja
OIDC_ISSUER={{ OIDC.CLIENT.ISSUER_URL }}
OIDC_DISCOVERY=true
OIDC_SCOPE=openid,profile,email
OIDC_UID_FIELD={{ OIDC.ATTRIBUTES.USERNAME }}
OIDC_CLIENT_ID={{ OIDC.CLIENT.ID }}
OIDC_CLIENT_SECRET={{ OIDC.CLIENT.SECRET }}
```

Every application role SHOULD follow the same shape: discovery on, the `OIDC.CLIENT.*` endpoints templated, the user identifier read from `OIDC.ATTRIBUTES.USERNAME`, and the scopes limited to what the app actually consumes.

## Related Files 📚

| File | Purpose |
|---|---|
| [11_oidc.yml](../../../../group_vars/all/11_oidc.yml) | OIDC SPOT, defines `OIDC.*` |
| [web-app-keycloak](../../../../roles/web-app-keycloak/) | OIDC provider role |
| [default.json.j2](../../../../roles/web-app-keycloak/templates/import/clients/default.json.j2) | Shared client template, MUST stay app-agnostic |
| [scopes](../../../../roles/web-app-keycloak/templates/import/scopes/) | Per-app client scopes for extra mappers |
| [realm.json.j2](../../../../roles/web-app-keycloak/templates/import/realm.json.j2) | Realm definition, including the `preferred_username` mapper |
| [ldap.md](ldap.md) | LDAP-side counterpart, paired user identifier |
| [common.md](common.md) | Cross-cutting IAM principles and integration checklist |
