# TODO

- Default model: the gateway serves `/v1` without a configured `model.default`; agent turns need `hermes config set model.default ollama/<alias>` against the LiteLLM-backed provider. Bake it via a config template once a turn-level e2e assertion exists.
- SSO: the API server authenticates with `API_SERVER_KEY` only; `services.sso` is dropped because an oauth2 proxy in front of the bearer API breaks OpenAI-compatible clients. Revisit if a browser dashboard surface appears upstream.
