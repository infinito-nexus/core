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
| `INFINITO_ALIAS_REPOSITORY` | Use your own terminal alias repository; see [terminal aliases](tools/shell/alias.md). |
| `INFINITO_SKILLS_REF` | Branch, tag or commit SHA of the skills repository that `make install-skills` installs. |
| `INFINITO_SKILLS_REPOSITORY` | Use your own agent skills repository, as URL or local path; `make install-skills` copies its skills into the project. A local path installs its committed state at `INFINITO_SKILLS_REF`, not its working tree. |
| `INFINITO_SKILLS_TARGETS` | Space-separated checkouts `make install-skills` installs into: `worktree` (the checkout you run it from) and `main` (the primary checkout, first in `git worktree list`). Each target also receives the running checkout's `agents/skills/`; `AGENTS.md` stays per branch. Example: `make install-skills INFINITO_SKILLS_TARGETS='worktree main'`. |
| `INFINITO_TEST_GPU` | `false` skips the GPU-only tests on a GPU host. Defaults to `true` where `INFINITO_GPU_COUNT` reserves a GPU, else `false`. |
