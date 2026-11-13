# Joomla 6 Keycloak OIDC SSO plugin (`plg_system_keycloak`)

Native OIDC SSO against Keycloak for Joomla 6, with RBAC group
mapping and an env-toggleable local-form fallback at
`/administrator?fallback=local` (Modus 3 per requirement 013).

## Build

The plugin's PHP dependencies (`jumbojett/openid-connect-php`) are
vendored at deploy time inside the Joomla container. Composer is
baked into the role's custom image by `roles/web-app-joomla/files/Dockerfile`.
The role-side `tasks/08_oidc_plugin.yml` copies the plugin source
into the container, runs `composer install --no-dev`, and installs
the plugin via the Joomla CLI:

```
php cli/joomla.php extension:install --path=/tmp/plg_system_keycloak
```

The repository working tree stays clean (no `vendor/` checked in)
and the host MUST NOT need a PHP or Composer installation.

## Configuration (env)

The plugin reads its runtime config from the Joomla container's
environment, so the same plugin code works against any Keycloak
realm without manual reconfiguration through the Joomla admin UI.

Every variable in the table is required; the plugin raises on a missing one instead of guessing a value.
`JOOMLA_OIDC_SOCKS_PROXY` is set only when the issuer is an onion address.
`templates/env.j2` renders them from the addon's `config:` block in `meta/addons/plg_system_keycloak.yml`.

| Variable                         | Purpose                                                                                                   |
|----------------------------------|-----------------------------------------------------------------------------------------------------------|
| `JOOMLA_OIDC_ISSUER_URL`         | Keycloak realm issuer URL.                                                                                |
| `JOOMLA_OIDC_CLIENT_ID`          | OIDC client ID in the realm.                                                                              |
| `JOOMLA_OIDC_CLIENT_SECRET`      | OIDC client secret.                                                                                       |
| `JOOMLA_OIDC_REDIRECT_URI`       | Callback URL `https://<joomla>/index.php?option=keycloak&task=callback`.                                  |
| `JOOMLA_OIDC_REDIRECT_URIS`      | JSON list of that callback on every network sibling, each with its scheme, from `lookup('network_urls')`. |
| `JOOMLA_OIDC_FALLBACK_ENABLED`   | If `false`, the local-form fallback at `/administrator?fallback=local` is disabled (Modus 1 in effect).    |
| `JOOMLA_OIDC_GROUP_MAP`          | JSON object of Keycloak group path to Joomla usergroup ID, built with `rbac_group_path`.                   |
| `JOOMLA_OIDC_CLAIM_USERNAME`     | Claim holding the login name, from `OIDC.ATTRIBUTES.USERNAME`.                                            |
| `JOOMLA_OIDC_CLAIM_EMAIL`        | Claim holding the email address, from `OIDC.ATTRIBUTES.EMAIL`.                                           |
| `JOOMLA_OIDC_CLAIM_GIVEN_NAME`   | Claim holding the given name, from `OIDC.ATTRIBUTES.GIVEN_NAME`.                                          |
| `JOOMLA_OIDC_CLAIM_FAMILY_NAME`  | Claim holding the family name, from `OIDC.ATTRIBUTES.FAMILY_NAME`.                                        |
| `JOOMLA_OIDC_CLAIM_LOCALE`       | Claim holding the locale, from `OIDC.ATTRIBUTES.LOCALE`.                                                  |
| `JOOMLA_OIDC_CLAIM_ZONEINFO`     | Claim holding the IANA time zone, from `OIDC.ATTRIBUTES.ZONEINFO`.                                        |
| `JOOMLA_OIDC_CLAIM_GROUPS`       | Groups claim and scope, from `RBAC.GROUP.CLAIM`.                                                          |
| `JOOMLA_OIDC_CLAIM_ADDRESS`      | Structured address claim, from `OIDC.ATTRIBUTES.ADDRESS`.                                                 |
| `JOOMLA_OIDC_PROFILE_CLAIMS`     | JSON object of `plg_user_profile` key to string claim (`phone`, `website`).                               |
| `JOOMLA_OIDC_PROFILE_ADDRESS_FIELDS` | JSON object of `plg_user_profile` key to member of the address claim (`address1`, `city`, `region`, `postal_code`, `country`). |
| `JOOMLA_OIDC_PROFILE_LOCKED`     | JSON list of the keys of the role's `sso.<claim>` fields in `meta/forms.yml`, the fields the plugin locks (see below); `templates/env.j2` renders it through `lookup('field_locks', application_id).profile`, not from the addon's `config:`. |
| `JOOMLA_OIDC_END_SESSION_URL`    | RP-initiated logout endpoint at Keycloak.                                                                 |
| `JOOMLA_ADMIN_USERNAME`          | Bootstrap administrator; the plugin keeps it in `Super Users` whatever its groups claim says.            |

The group map covers the `administrator` (Super Users, id 8), `manager` (Manager, id 6), `publisher` (Publisher, id 5), `editor` (Editor, id 4), `author` (Author, id 3) and `registered` (Registered, id 2) roles.
A user whose groups claim matches none of them lands in the com_users "New User Registration Group" (`new_usertype`, `Registered` by default).
The Joomla account is created on first login if it does not already exist.
Every login re-syncs the group memberships, name, email, frontend language and time zone from Keycloak.
The `locale` claim maps to the installed site language with the same tag, then to the first installed language with the same primary subtag (`de` resolves to `de-DE`), else to the site default.
The `zoneinfo` claim maps to the time zone when PHP knows it, else to the site default.
The plugin requests the `phone` and `address` scopes and writes the mapped claims into the `profile` data that the core `plg_user_profile` stores; a claim the ID token does not carry clears its field.
Every login stores the name through the `string` input filter and the email in its punycode form, the values the com_users profile save produces, marks the account with the `keycloak_managed` user parameter, forks the session and marks it with `keycloak.sso_session`. A local sign-in clears that mark (`onUserAfterLogin`); for a marked account other than the bootstrap administrator (`JOOMLA_ADMIN_USERNAME`) it signs the account out again and sends it to `task=login`, so a marked account holds a site session through Keycloak only. The com_users profile form of a marked account renders the fields `JOOMLA_OIDC_PROFILE_LOCKED` names read-only and marks each with `data-infinito-sso-locked` (`onContentPrepareForm`, after every other plugin), and a profile save keeps their stored values (`onContentNormaliseRequestData`); a local session of the bootstrap administrator or of an account holding `core.admin` is break-glass and edits its own profile freely. `onUserBeforeSave` throws when a site request outside the break-glass session or a web services API request changes a locked field or `keycloak_managed` of a marked account; the callback's own provisioning write, the console and the backend pass. A field whose key `JOOMLA_OIDC_PROFILE_LOCKED` does not list stays editable; the next login still overwrites it. The backend is break-glass only: the callback runs on the site client, so a backend session never carries `keycloak.sso_session` and its user form is not locked. The selectors of the role's `sso.<claim>` fields match the marker, so the shared lock renderer adds the warning only to fields the plugin locked.
A valid com_users `user.logout` request of a signed-in site user takes the `task=logout` path below.

### Locked fields

`lockTargets()` resolves each key of `JOOMLA_OIDC_PROFILE_LOCKED`:

| Key             | Form field (group)                 | Stored in                                                         |
|-----------------|------------------------------------|-------------------------------------------------------------------|
| `name`          | `name`                             | users column `name`                                               |
| `username`      | `username`                         | users column `username`                                           |
| `email`         | `email1`                           | users column `email`                                              |
| `language`      | `language` (`params`)              | user param `language`                                             |
| `timezone`      | `timezone` (`params`)              | user param `timezone`                                             |
| `address`       | every key of `JOOMLA_OIDC_PROFILE_ADDRESS_FIELDS` (`profile`) | those `plg_user_profile` keys                |
| any other key   | the key itself (`profile`)         | the `plg_user_profile` key of that name in `JOOMLA_OIDC_PROFILE_CLAIMS` (`phone`, `website`) |

A key that resolves to none of them, an empty list, or a value that is no JSON list of names makes the plugin raise and name the variable or the key. `keycloak_managed` stays guarded whatever the list holds.

## Routes the plugin claims

| URL                                       | Purpose                                  |
|-------------------------------------------|------------------------------------------|
| `/index.php?option=keycloak&task=login`   | Start the OIDC authorization-code flow.  |
| `/index.php?option=keycloak&task=callback`| OIDC callback endpoint.                  |
| `/index.php?option=keycloak&task=logout`  | RP-initiated logout against Keycloak, also taken by the com_users Log out button. |
| `/index.php?fallback=local`               | Local Joomla form-login (Modus 3 hatch). |

## Watch points

- The plugin trusts the Keycloak-issued ID token. The
  `jumbojett/openid-connect-php` library validates the JWT signature
  against the realm's JWKS, so the issuer URL MUST be reachable
  from the Joomla container at the time the user authenticates.
- The plugin lives in the `system` plugin group so it can intercept
  every request via `onAfterInitialise`. It MUST run BEFORE the
  Joomla local form-login plugin in the system event chain so the
  redirect short-circuits any local-account authentication attempt.
  System plugins are ordered alphabetically. `keycloak` ranks
  before `users`, which is the typical local-form gate.
- The local-form fallback at `?fallback=local` is documented as an
  emergency hatch. For high-security deployments, set
  `JOOMLA_OIDC_FALLBACK_ENABLED=false` to disable it (Modus 1
  effective).
