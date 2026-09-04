# TODO

- Administrator persona: `PERSONA_ADMINISTRATOR_BLOCKED=true` because the Control UI is a WebSocket SPA whose session lives behind gateway device pairing; there is no DOM logout control the shared `inAppLogout` helper can reach. The SSO round-trip itself is covered by `test-oidc-login.js`. Unblock once the Control UI exposes a plain logout affordance or the persona helpers learn the pairing handshake.
- MCP client wiring: the native `@modelcontextprotocol/sdk` client is configured through `openclaw.json`, not env.
