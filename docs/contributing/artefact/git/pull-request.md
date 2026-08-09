# Pull Request 🔀

## Templates 📋

You MUST pick the template that matches your change. The table below links the actual templates.

| Change type | Template |
|---|---|
| Server and `web-*` changes | [server.md](../../../../.github/PULL_REQUEST_TEMPLATE/server.md) |
| Workstation and `desk-*` changes | [workstation.md](../../../../.github/PULL_REQUEST_TEMPLATE/workstation.md) |
| Shared system changes such as `sys-*`, `svc-*`, `dev-*`, `drv-*`, `pkgmgr`, `update-*`, or `user-*` | [system.md](../../../../.github/PULL_REQUEST_TEMPLATE/system.md) |
| CI/CD and workflow changes | [pipeline.md](../../../../.github/PULL_REQUEST_TEMPLATE/pipeline.md) |
| Documentation-only changes limited to `.md` or `.rst` files outside `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, and `docs/agents/*` | [documentation.md](../../../../.github/PULL_REQUEST_TEMPLATE/documentation.md) |
| Agent-specific changes limited to `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, or `docs/agents/*` | [agents.md](../../../../.github/PULL_REQUEST_TEMPLATE/agents.md) |

## Branch Naming 🏷️

Branch names MUST follow the naming conventions defined in [branch.md](branch.md). The branch prefix MUST match the type of change and is used to classify the PR scope and select the CI pipeline.

The protection rules enforced on `main` are documented in [branch.md](../../tools/github/branch/security.md).

## Forking Flow 🍴

Before marking a PR as **ready for review**, CI in your fork MUST be green. The required scope depends on what you changed:

| Change type | Isolated? | Required CI |
|---|---|---|
| Single role | ✅ No dependencies | MAY use [manual CI](../../../../.github/workflows/entry-manual-steer.yml) for that role only |
| Single role | ❌ Has dependencies | MUST run full pipeline |
| Multiple roles or shared code | N/A | MUST run full pipeline |
| CI/CD, tooling, systemic | N/A | MUST run full pipeline |

If you are unsure whether other roles are affected, you MUST run the full pipeline.

## Drafts 📝

You SHOULD open a Pull Request as a **draft** while your change is still in progress. CI will not run and no reviewer time is spent until you mark it ready.

- You MUST mark the PR **ready for review** before requesting a review. CI starts automatically at that point.
- If you continue working on the PR after marking it ready, you MUST convert it back to a **draft** before pushing new commits. Otherwise CI triggers on every push to the main repository.
- You MAY convert it back to a **draft** at any time. Any running CI jobs will be cancelled immediately.

## Checklist ✅

Before you open a Pull Request:

- CI in your fork MUST be green.
- Your branch MUST be up to date with `main`.
- Your change SHOULD be small and focused.
- Relevant documentation MUST be updated.
- The correct Pull Request template MUST be used.
- The Pull Request MUST be linked to the related work item in [project.infinito.nexus](https://project.infinito.nexus/) and back.
- Screenshots, logs, traces, or migration notes SHOULD be attached when they help review the change.
