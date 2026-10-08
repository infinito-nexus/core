# TODO

- Default model: the gateway serves `/v1` without a configured `model.default`; agent turns need `hermes config set model.default ollama/<alias>` against the LiteLLM-backed provider. Bake it via a config template once a turn-level e2e assertion exists.
- Dashboard settings: the deploy copies `/opt/data/config.yaml` onto the data volume on every container start, so a key the dashboard writes survives until the next deploy overwrites it. Decide which keys the deploy owns and whether the remaining ones move to a location it does not rewrite.
- Documentation tab: the dashboard embeds the upstream documentation site in a frame, which the content security policy blocks (`frame-src 'self'`), and `/docs` on a full page load serves the API reference whose assets load from a third-party CDN that the policy blocks as well.
