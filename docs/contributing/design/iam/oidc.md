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
| `OIDC.ATTRIBUTES.NAME` | `name` | Full name |
| `OIDC.ATTRIBUTES.GIVEN_NAME` | `given_name` | First name |
| `OIDC.ATTRIBUTES.FAMILY_NAME` | `family_name` | Last name |
| `OIDC.ATTRIBUTES.MIDDLE_NAME` | `middle_name` | Middle name |
| `OIDC.ATTRIBUTES.NICKNAME` | `nickname` | Preferred display name, never a login identifier |
| `OIDC.ATTRIBUTES.EMAIL` | `email` | Email address |
| `OIDC.ATTRIBUTES.PHONE_NUMBER` | `phone_number` | Phone number, needs the `phone` scope |
| `OIDC.ATTRIBUTES.ADDRESS` | `address` | Postal address object, needs the `address` scope |
| `OIDC.ATTRIBUTES.LOCALE` | `locale` | Preferred language |
| `OIDC.ATTRIBUTES.ZONEINFO` | `zoneinfo` | IANA time zone |
| `OIDC.ATTRIBUTES.WEBSITE` | `website` | Website |

`OIDC.ADDRESS_CLAIMS` names the members of the `OIDC.ATTRIBUTES.ADDRESS` object: `STREET` (`street_address`), `LOCALITY` (`locality`), `REGION` (`region`), `POSTAL_CODE` (`postal_code`) and `COUNTRY` (`country`).

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
`roles/web-app-keycloak/templates/import/clients/`. The
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

## oauth2-proxy Gate 🚧

A role with `services.sso.flavor: oauth2` sits behind an oauth2-proxy sidecar that web-app-keycloak renders from two files per network: a [core config](../../../../roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak.cfg.j2) (cookie, session, domains) and an [alpha config](../../../../roles/web-app-keycloak/templates/sso_proxy/oauth2-proxy-keycloak-alpha.yml.j2) (provider, upstream, headers).
nginx asks the gate per request (`auth_request`) and hands the upstream these headers:

| Header | Content |
|---|---|
| `X-Forwarded-User`, `X-Forwarded-Email`, `X-Forwarded-Preferred-Username` | Identity of the signed-in user |
| `X-Forwarded-Groups` | The `RBAC.GROUP.CLAIM` paths |
| `X-Forwarded-Access-Token` | Only with `services.sso.oauth2.pass_access_token: true` |
| `X-Forwarded-<Key>` | One per `OIDC.ATTRIBUTES` key listed in `services.sso.oauth2.claim_headers` |

`claim_headers` takes `OIDC.ATTRIBUTES` keys, for example:

```yaml
sso:
  flavor: oauth2
  oauth2:
    claim_headers: [NAME, LOCALE, ZONEINFO]
```

The gate reads each listed claim from the ID token and forwards it as `X-Forwarded-Name`, `X-Forwarded-Locale` and `X-Forwarded-Zoneinfo`; a key with an underscore becomes a dashed header (`PHONE_NUMBER` → `X-Forwarded-Phone-Number`).
`USERNAME` and `EMAIL` are already forwarded, and `ADDRESS` is an object claim, so the three are refused.
nginx clears every forwardable `X-Forwarded-<Key>` an application did not declare, so a client cannot inject one.

`services.sso.oauth2.allowed_groups` restricts the whole application. To restrict one path further, list it under `restricted_locations`:

```yaml
sso:
  flavor: oauth2
  oauth2:
    restricted_locations:
      - location: "/admin"
        groups:
          - "{{ lookup('rbac_group_path', application_id='web-app-magento', role='administrator') }}"
```

The vhost then asks the gate through an internal `/oauth2/auth-restricted-<n>` location that forwards to `/oauth2/auth?allowed_groups=<groups>`. A signed-in user outside the groups gets HTTP 403 on that path and keeps every other path.

## Related Files 📚

| File | Purpose |
|---|---|
| [11_oidc.yml](../../../../group_vars/all/11_oidc.yml) | OIDC SPOT, defines `OIDC.*` |
| [web-app-keycloak](../../../../roles/web-app-keycloak/) | OIDC provider role |
| [default.json.j2](../../../../roles/web-app-keycloak/templates/import/clients/default.json.j2) | Shared client template, MUST stay app-agnostic |
| `roles/web-app-keycloak/templates/import/scopes/` | Per-app client scopes for extra mappers |
| [realm.json.j2](../../../../roles/web-app-keycloak/templates/import/realm.json.j2) | Realm definition, including the `preferred_username` mapper |
| [ldap.md](ldap.md) | LDAP-side counterpart, paired user identifier |
| [common.md](common.md) | Cross-cutting IAM principles and integration checklist |
