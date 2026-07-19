# Agent Aliases ⌨️

This file defines the Infinito.Nexus-specific shortcuts operators use in conversations with the agent.
When an operator message contains a shortcut from the table below, the agent MUST expand it to the listed meaning and MUST act on the expanded instruction.

Portable, project-agnostic shortcuts (commit, stage, `make test`, …) live in the `shortcuts` skill from the [skills](https://github.com/kevinveenbirkenbach/skills) repository, installed via `make install-skills`.

Run `make alias` to print these shortcuts, the portable ones, and the [terminal aliases](../shell/alias.md) on the CLI.
The effective table is the `INFINITO_ALIAS_MD` value in the generated `.env`; override it via `custom.env` as described in [customize.md](../../customize.md) to use your own table.
A custom table MUST use the same markdown table format with backtick-quoted shortcuts in the first column.
Every shortcut MUST start with `ai8` and MUST NOT place two consonants next to each other in its name.
The table MUST stay sorted ascending by shortcut and its shortcuts MUST NOT collide with the effective [terminal aliases](../shell/alias.md); the test suite enforces all of this against the generated `.env`.

## Shortcuts 📋

| Shortcut | Meaning |
| --- | --- |
| `ai8co` | Iterate on a role in compose mode via the `i8-iteration-compose` skill. |
| `ai8ma` | Run `make autoformat`. |
| `ai8pa` | Iterate on a role's Playwright spec via the `i8-iteration-playwright` skill. |
| `ai8qu` | Run `make quality`. |
| `ai8ro` | Cross-mode roundtrip validation via the `i8-iteration-roundtrip` skill. |
| `ai8ru` | Iterate on svc-runner or the CI runner infrastructure via the `i8-iteration-runner` skill. |
| `ai8wa` | Iterate on a role in swarm mode via the `i8-iteration-swarm` skill. |
| `ai8wo` | Iterate on a GitHub Actions workflow via the `i8-iteration-workflow` skill. |
