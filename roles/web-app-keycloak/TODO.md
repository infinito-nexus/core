# Todos

- Implement working logout for all applications
- Implement general logout button

## Req 019 rollout: deploy gate

- During the autonomous req 019 rollout, `make compose-deploy mode=reinstall apps=web-app-keycloak full_cycle=true` failed with two unrelated assertions:
  - `kcadm.sh config credentials` failed during the keycloak admin login phase (likely transient or env-scoped).
  - `run_once_web_app_mailu is defined` assertion failed in `sys-svc-mail`, indicating the service-loader did not preload Mailu in the keycloak-only deploy path.
- These are deployment-orchestration failures, not playwright-parity failures, and were therefore deferred per the autonomy escape clause (archived req 019).
- The role's playwright lint contracts (Tests A + B + env_keys_used) are green; role-closure remains pending the orchestration fix.

## Trusted-header SSO bridge migration

Roles still to migrate to the trusted-header SSO bridge (pattern: `web-app-baserow` / `web-app-bookwyrm`):

- `web-app-kix` — native OTRS header-auth module
- `web-app-friendica` — addon/hook: header → session
- `web-app-akaunting` — Laravel controller shim (stage shim into the named volume on every deploy)
- `web-app-magento` — custom `Infinito_HeaderSso` module (bypass FPC/Varnish on the handoff route)
- `web-app-suitecrm` — header → session shim
- `web-app-funkwhale` — django header / remote-user auth backend
- Excluded: `web-app-flowise` (session-minting code is commercial-licensed), `web-app-jitsi` (no HTTP session — use native `AUTH_TYPE=jwt`)
