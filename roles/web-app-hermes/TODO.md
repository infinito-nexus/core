# TODO

- MCP client wiring: `services.mcp` declares the client intent, but Hermes reads MCP servers from its config store (`hermes mcp add`), not from env. Template `~/.hermes` MCP config from `lookup('roles_with_service', 'mcp', direction='server')` once the config-file contract is exercised end to end.
- Default model: the gateway serves `/v1` without a configured `model.default`; agent turns need `hermes config set model.default ollama/<alias>` against the LiteLLM-backed provider. Bake it via a config template once a turn-level e2e assertion exists.
- SSO: the API server authenticates with `API_SERVER_KEY` only; `services.sso` is dropped because an oauth2 proxy in front of the bearer API breaks OpenAI-compatible clients. Revisit if a browser dashboard surface appears upstream.
