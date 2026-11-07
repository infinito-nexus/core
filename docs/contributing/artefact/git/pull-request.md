# Pull Request 🔀

## Template 📋

Every pull request body MUST come from the one template [pull_request_template.md.j2](../../../../.github/pull_request_template.md.j2). Its area is chosen through the `scope` variable:

| `scope` | Change type | Web template |
|---|---|---|
| `server` | Server and `web-*` changes | [server.md](../../../../.github/PULL_REQUEST_TEMPLATE/server.md) |
| `workstation` | Workstation and `dsk-*` changes | [workstation.md](../../../../.github/PULL_REQUEST_TEMPLATE/workstation.md) |
| `system` | Shared system changes such as `sys-*`, `svc-*`, `dev-*`, `drv-*`, `pkgmgr`, `update-*`, or `user-*` | [system.md](../../../../.github/PULL_REQUEST_TEMPLATE/system.md) |
| `pipeline` | CI/CD and workflow changes | [pipeline.md](../../../../.github/PULL_REQUEST_TEMPLATE/pipeline.md) |
| `documentation` | Documentation-only changes limited to `.md` or `.rst` files outside `AGENTS.md` and `agents/*` | [documentation.md](../../../../.github/PULL_REQUEST_TEMPLATE/documentation.md) |
| `agents` | Agent-specific changes limited to `AGENTS.md` or `agents/*` | [agents.md](../../../../.github/PULL_REQUEST_TEMPLATE/agents.md) |
| `general` | Changes spanning several of the areas above | agents only |

- In the web UI, GitHub fills a new pull request with [pull_request_template.md](../../../../.github/pull_request_template.md), a short chooser, and offers no other template choice. Add `template=<area>.md` to the address of the pull request page, for example `?quick_pull=1&template=server.md`, and reload to get the template of your area.
- These web templates are generated from the one template for the `human` audience. You MUST NOT edit them by hand; regenerate them with `python -m cli.contributing.pull_request default`. The lint [test_pull_request_template_current.py](../../../../tests/lint/repository/test_pull_request_template_current.py) fails when one is not the current render.
- Agents MUST render the body with `python -m cli.contributing.pull_request render --values <file> --output <file>`, never by editing prose. The renderer validates every value before it renders.

### Contract 🤝

Any renderer of this template, the repository's own and an external one, MUST follow these rules:

- Path: `.github/pull_request_template.md.j2`, relative to the repository root. When it is absent, a renderer falls back to its own template.
- Syntax: Jinja2 with `StrictUndefined`, `trim_blocks`, `lstrip_blocks`, `keep_trailing_newline` and no autoescaping.
- Every variable below MUST be passed. A missing one fails the render loudly; there are no defaults. `null` or an empty list renders the area's prompt text instead of a value.
- The area data (labels, checklist ids, prompts) lives in the `AREAS` mapping at the top of the template, so a check id is valid only for the area that lists it.
- The `score_table` value is the `--table` output of the `kvb-check-score` skill, passed verbatim. A commit message carries the multi-line `--message-block` form of the same score instead.

### Variables 🔤

| Variable | Type | Meaning |
|---|---|---|
| `audience` | `agent` or `human` | `agent` renders one area with its values. `human` renders the web templates: the chooser for `general`, the area's prompts for every other scope. |
| `scope` | `AREAS` key | The area from the table above. |
| `title` | string | The Conventional Commits title, rendered as the H1. |
| `summary` | string | The change and its effect. |
| `closes` | list of issue numbers | One `Closes #<n>` line each. |
| `intent` | `feature` or `fix` | Ticks the matching intent box. |
| `components` | list of strings | The affected roles, modules or files. |
| `integrations` | list of strings | Server only: the preferred integrations the change covers. |
| `files` | list of check ids | Server only: the rows of the file checklist and the registered table that apply. |
| `roles` | list of role ids | The `🧩 Subset` roles; empty keeps the commented examples. Areas without a subset block take only an empty list. |
| `semver` | `major`, `minor` or `patch` | Ticks the matching change type box. |
| `details` | string | What changed and why. |
| `checks` | list of check ids | The validation checks of the area that hold. |
| `evidence` | string | The test evidence: commands run and their results. |
| `security_impact` | boolean | Ticks one of the two security boxes. |
| `security_notes` | string | The explanation when `security_impact` is true, otherwise `null`. |
| `review_focus` | list of strings | Where reviewers should look first. |
| `score_table` | string | The `kvb-check-score` table; `null` omits the section. |
| `dod` | boolean | Ticks the Definition of Done box. |
| `notes` | string | Additional reviewer context. |

For the `agent` audience every string except `security_notes` MUST be non-empty, `components` MUST NOT be empty, and `intent`, `semver` and `security_impact` MUST be set.

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
- The body MUST be rendered from the template with the `scope` of your change.
- The Pull Request MUST be linked to the related work item in [project.infinito.nexus](https://project.infinito.nexus/) and back.
- Screenshots, logs, traces, or migration notes SHOULD be attached when they help review the change.
