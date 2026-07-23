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

| Variable                       | Purpose                                                                                                | Default                                          |
|--------------------------------|--------------------------------------------------------------------------------------------------------|--------------------------------------------------|
| `JOOMLA_OIDC_ISSUER_URL`       | Keycloak realm issuer URL.                                                                             | (required)                                       |
| `JOOMLA_OIDC_CLIENT_ID`        | OIDC client ID in the realm.                                                                           | (required)                                       |
| `JOOMLA_OIDC_CLIENT_SECRET`    | OIDC client secret.                                                                                    | (required)                                       |
| `JOOMLA_OIDC_REDIRECT_URI`     | Callback URL `https://<joomla>/index.php?option=keycloak&task=callback`.                               | (required)                                       |
| `JOOMLA_OIDC_FALLBACK_ENABLED` | If `false`, the local-form fallback at `/administrator?fallback=local` is disabled (Modus 1 in effect). | `true`                                           |
| `JOOMLA_OIDC_GROUP_ADMIN`      | Keycloak group path that maps onto Joomla's `Super Users` (id 8).                                      | `/roles/web-app-joomla/administrator`            |
| `JOOMLA_OIDC_GROUP_EDITOR`     | Keycloak group path that maps onto Joomla's `Editor` (id 4).                                           | `/roles/web-app-joomla/editor`                   |
| `JOOMLA_OIDC_GROUP_USER`       | Keycloak group path that maps onto Joomla's `Registered` (id 2).                                       | `/roles/web-app-joomla`                          |
| `JOOMLA_OIDC_END_SESSION_URL`  | RP-initiated logout endpoint at Keycloak.                                                              | `<issuer>/protocol/openid-connect/logout`        |

A user whose Keycloak `groups` claim matches none of the three
mapped paths is refused. This is the documented RBAC gate per
requirement 013. The Joomla account is created on first login if it
does not already exist. Subsequent logins re-sync the group
memberships from Keycloak.

## Routes the plugin claims

| URL                                       | Purpose                                  |
|-------------------------------------------|------------------------------------------|
| `/index.php?option=keycloak&task=login`   | Start the OIDC authorization-code flow.  |
| `/index.php?option=keycloak&task=callback`| OIDC callback endpoint.                  |
| `/index.php?option=keycloak&task=logout`  | RP-initiated logout against Keycloak.    |
| `/index.php?fallback=local`               | Local Joomla form-login (Modus 3 hatch). |

## Watch points

* The plugin trusts the Keycloak-issued ID token. The
  `jumbojett/openid-connect-php` library validates the JWT signature
  against the realm's JWKS, so the issuer URL MUST be reachable
  from the Joomla container at the time the user authenticates.
* The plugin lives in the `system` plugin group so it can intercept
  every request via `onAfterInitialise`. It MUST run BEFORE the
  Joomla local form-login plugin in the system event chain so the
  redirect short-circuits any local-account authentication attempt.
  System plugins are ordered alphabetically. `keycloak` ranks
  before `users`, which is the typical local-form gate.
* The local-form fallback at `?fallback=local` is documented as an
  emergency hatch. For high-security deployments, set
  `JOOMLA_OIDC_FALLBACK_ENABLED=false` to disable it (Modus 1
  effective).
