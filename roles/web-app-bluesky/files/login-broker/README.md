# Bluesky login-broker

OIDC to Bluesky-PDS app-password broker (variant A+ per requirement
013, web-app-bluesky per-role notes).

The broker sits behind `web-app-keycloak`'s SSO-proxy sidecar and in front of the
official `@bluesky-social/social-app` web client. On a user's first
OIDC-authenticated visit, the broker:

1. Looks up the Keycloak user via the Admin REST API. The
   service-account credentials are mounted as env, see `KC_ADMIN_*`.
2. Provisions a Bluesky PDS account via
   `com.atproto.server.createAccount` if no encrypted app-password is
   recorded on the user yet, encrypts the synthesised app-password
   with **AES-256-GCM**, and stores the ciphertext as the
   `bluesky_app_password_enc` user attribute.
3. Decrypts the stored app-password in-process and exchanges it for
   a PDS session via `com.atproto.server.createSession`.
4. Renders an HTML handoff page that drops the resulting session
   JWTs into `localStorage["BSKY_STORAGE"]` (the canonical
   `social-app` storage key), sets a short-lived
   `bsky_handoff_done=1` cookie, and redirects to `/`.

For subsequent requests carrying that cookie, the broker reverse-
proxies to the `social-app` upstream so the user appears to log in
to Bluesky purely via Keycloak SSO without ever seeing the
synthesised app-password.

## Required environment

| Variable                          | Purpose                                                                   |
|-----------------------------------|---------------------------------------------------------------------------|
| `BROKER_PORT`                     | TCP port to listen on (default `8080`).                                   |
| `SOCIAL_APP_URL`                  | Reverse-proxy upstream (`http://web:8100`).                               |
| `PDS_URL`                         | Public Bluesky PDS base URL (`https://api.bluesky.<domain>`), written into the browser `service` field. |
| `PDS_INTERNAL_URL`                | In-stack PDS URL for server-side XRPC calls (`http://pds:3000`); defaults to `PDS_URL` when unset.       |
| `PDS_HANDLE_DOMAIN`               | Suffix for synthesised handles (`<DOMAIN_PRIMARY>`).                      |
| `PDS_INVITE_CODE`                 | Optional invite code for gated PDS deployments.                           |
| `KC_ADMIN_BASE_URL`               | Keycloak base URL (`https://auth.<domain>`).                              |
| `KC_ADMIN_REALM`                  | Realm of the broker's service account (typically the same as user realm).|
| `KC_ADMIN_CLIENT_ID`              | Service-account client ID.                                                |
| `KC_ADMIN_CLIENT_SECRET`          | Service-account client secret.                                            |
| `KC_USER_REALM`                   | Realm where end-user accounts live (typically same as admin realm).       |
| `BLUESKY_BRIDGE_ENCRYPTION_KEY`   | base64-encoded 32 random bytes; AES-256-GCM key.                          |
| `HANDOFF_COOKIE_NAME`             | Override the cookie name (default `bsky_handoff_done`).                   |
| `HANDOFF_COOKIE_MAX_AGE`          | Cookie lifetime in seconds (default `3300`, roughly 55 minutes).          |
| `INSECURE_TLS`                    | If `true`, skip TLS verification on outbound calls (for local CA).        |

## Forwarded identity

The upstream `oauth2-proxy` MUST set `X-Forwarded-User` (or
`X-Forwarded-Preferred-Username`) and `X-Forwarded-Email` on every
request that reaches the broker. Without `X-Forwarded-User`, the
broker returns HTTP 401, there is no anonymous fallback by design.

## Failure modes

* **PDS unreachable:** the broker bubbles up the createAccount or
  createSession failure and the user sees an HTML error page on the
  handoff route. Re-trying the visit after PDS recovery completes
  the handoff.
* **Encrypted attribute decrypt failure:** indicates a key mismatch
  between the SPI and the broker. The broker rejects the request
  with HTTP 500 rather than risk silently re-provisioning a fresh
  PDS account that loses the user's existing posts. Recovery: rotate
  the key and clear the attribute (manual op for now, key rotation
  is in the doc 013 Future Hardening section).
* **social-app upstream error:** the broker forwards the upstream's
  error response.
