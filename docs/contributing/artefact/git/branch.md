# Branch 🌿

## CI Impact 🔀

The branch prefix MUST match the type of change. The [PR workflow](pull-request.md) uses it to classify the scope and decide which CI pipeline to run.

| Branch prefix | Scope | Matching files | CI behavior |
|---|---|---|---|
| `agent` | Changes to agent instructions or prompts | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `docs/agents/*` | Skips [ci-orchestrator](../../../../.github/workflows/ci-orchestrator.yml), finishes green through the lightweight scope gate. |
| `documentation` | Documentation-only changes | `**/*.md`, `**/*.rst` (outside agent paths) | Skips [ci-orchestrator](../../../../.github/workflows/ci-orchestrator.yml), finishes green through the lightweight scope gate. |
| `feature` | New features or enhancements | `*` | Runs the full [ci-orchestrator](../../../../.github/workflows/ci-orchestrator.yml) pipeline. |
| `fix` | Bug fixes | `*` | Runs the full [ci-orchestrator](../../../../.github/workflows/ci-orchestrator.yml) pipeline. |
| `update` | Automated or maintenance updates | `*` | Runs the full [ci-orchestrator](../../../../.github/workflows/ci-orchestrator.yml) pipeline. |
| `chore` | Maintenance, dependency, and tooling updates (incl. branches created by [update.yml](../../../../.github/workflows/update.yml)) | `*` | Runs the full [ci-orchestrator](../../../../.github/workflows/ci-orchestrator.yml) pipeline. |
| `alert-autofix` | Automated alert-triggered fixes | `*` | Runs the full [ci-orchestrator](../../../../.github/workflows/ci-orchestrator.yml) pipeline. |
| `dependabot` | Automated dependency updates | `*` | Runs the full [ci-orchestrator](../../../../.github/workflows/ci-orchestrator.yml) pipeline. |

## Enforcement 🔒

All rules in this document are actively enforced on `main` via GitHub branch protection. See [branch.md](../../tools/github/branch/security.md) for the full enforcement policy.

The naming conventions below are additionally checked locally by the lint test [test_branch_name.py](../../../../tests/lint/repository/naming/test_branch_name.py), which fails `make test-lint` when the checked-out branch uses an unknown prefix (e.g. `feat/` instead of `feature/`) or a non-kebab-case description.

## Naming Conventions 🏷️

The description MUST use `kebab-case` (lowercase words separated by hyphens) and SHOULD be short enough to read at a glance.

The full branch name MUST follow one of the patterns below, depending on whether the change targets a specific role or is general:

| Case | Pattern | Example |
|---|---|---|
| General feature | `feature/<topic>` | `feature/ldap-integration` |
| Role feature | `feature/<role>/<topic>` | `feature/web-app-matomo/ldap-integration` |
| General fix | `fix/<topic>/<ticket-id>` | `fix/dns-resolution/taiga-123` |
| Role fix | `fix/<role>/<topic>/<ticket-id>` | `fix/web-app-matomo/login-redirect/taiga-789` |
| General update | `update/<topic>` | `update/docker-image-versions` |
| Chore | `chore/<topic>` | `chore/update-docker-image-versions` |
| Alert autofix | `alert-autofix-<alert-id>` | `alert-autofix-261` |
| Documentation | `documentation/<topic>` | `documentation/contributing-setup` |
| Agent | `agent/<topic>` | `agent/improve-commit-instructions` |
| Dependabot | `dependabot/<ecosystem>/<dependency>` | `dependabot/pip/requests-2.32.0` |

`feature`, `update`, `documentation`, and `agent` branches MUST NOT reference a ticket ID.
`alert-autofix` branches reference the alert ID instead of a ticket ID.
`dependabot` branches are created automatically and MUST NOT be renamed.
