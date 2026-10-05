# TODO

- Administrator persona: `PERSONA_ADMINISTRATOR_BLOCKED=true` because the Control UI is a WebSocket SPA whose session lives behind gateway device pairing; there is no DOM logout control the shared `inAppLogout` helper can reach. The SSO round-trip itself is covered by `test-oidc-login.js`. Unblock once the Control UI exposes a plain logout affordance or the persona helpers learn the pairing handshake.
- MCP client wiring: the native `@modelcontextprotocol/sdk` client is configured through `openclaw.json`, not env.
- Dashboard tests: the gateway pairs every new browser through `openclaw devices approve`, so the dashboard design test and the dashboard views of the gallery run only for a browser an operator approved, and skip themselves otherwise. `gateway.auth.mode: trusted-proxy` behind the OAuth2 proxy would admit the signed-in administrator without pairing and let these tests run unattended.
- Product name: the `aria-label` of the top bar brand and the `alt` text of the login logo still read `OpenClaw`; the Control UI offers no setting for its name, and the stylesheet replaces only the visible text.
