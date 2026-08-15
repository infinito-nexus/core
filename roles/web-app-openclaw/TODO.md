# TODO

- Administrator persona: `PERSONA_ADMINISTRATOR_BLOCKED=true` because the Control UI is a WebSocket SPA whose session lives behind gateway device pairing; there is no DOM logout control the shared `inAppLogout` helper can reach. The SSO round-trip itself is covered by `test-oidc-login.js`. Unblock once the Control UI exposes a plain logout affordance or the persona helpers learn the pairing handshake.
- Model wiring: OpenClaw reads model providers from `openclaw.json` (`models.providers`), not from env, so `services.litellm` currently only shapes the deploy topology. Template `/home/node/.openclaw/openclaw.json` with a LiteLLM-backed OpenAI-compatible provider (using `credentials.litellm_api_key`) once the config-file schema is exercised end to end.
- MCP client wiring: same situation as the model config; the native `@modelcontextprotocol/sdk` client is configured through `openclaw.json`, not env.
