# TODO

- Default model: the gateway serves `/v1` without a configured `model.default`; agent turns need `hermes config set model.default ollama/<alias>` against the LiteLLM-backed provider. Bake it via a config template once a turn-level e2e assertion exists.
- Dashboard settings: `/opt/data/config.yaml` is mounted as a single file, so the dashboard answers a theme save with HTTP 500. Decide which keys the deploy owns and whether the remaining ones move to a writable location.
- Documentation tab: the dashboard embeds the upstream documentation site in a frame, which the content security policy blocks (`frame-src 'self'`), and `/docs` on a full page load serves the API reference whose assets load from a third-party CDN that the policy blocks as well.
