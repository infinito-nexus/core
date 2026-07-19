# Customize 🧩

The generated `.env` is the single effective configuration source for all tooling.
`make dotenv` composes it from `default.env`, the environment handlers, and finally your personal `custom.env`.

## custom.env 🗝️

1. Create `custom.env` in the repository root (untracked); use [default.env](../../default.env) as the reference for available keys.
2. Add only the `INFINITO_*` keys you want to change.
3. Run `make dotenv`.

Values from `custom.env` are applied last, so they override `default.env` and every handler-computed value.
Keys MUST already be registered (a default in `default.env` or a handler under `utils/env/handlers/`); unknown keys fail the env lint.

## Common Overrides ⚙️

| Key | Effect |
| --- | --- |
| `INFINITO_ALIAS_MD` | Use your own agent shortcut table; see [agent aliases](tools/agents/alias.md). |
| `INFINITO_ALIAS_REPOSITORY` | Use your own terminal alias repository; see [terminal aliases](tools/shell/alias.md). |
| `INFINITO_SKILLS_REPOSITORY` | Use your own agent skills repository; `make install-skills` copies its skills into the project. |
