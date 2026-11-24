# Cheatsheet 📋

Each operator workflow has a skill that routes the agent to its authoritative
procedure and drives it — clarifying open requirements first, then acting
autonomously to completion. Most are `i8-` skills specific to this repository; a
few (such as `triage`) are portable skills shared across projects.

## How to use 🧭

Invoke a skill with its slash command, for example `/i8-develop` or `/i8-quality`,
or name the skill in your message to the agent. Supply the concrete target (role,
scope, requirement file, or run URL) in the same message; the skill fills the rest
from its procedure file. Run `make install-skills` to (re)install them; `INFINITO_SKILLS_TARGETS`, `INFINITO_SKILLS_REF` and `INFINITO_SKILLS_REPOSITORY` choose the checkouts and the skills version, see [customize.md](../../customize.md).

## Skills 🗂️

| Situation | Skill |
|---|---|
| Building a new feature, app, or larger change | `i8-develop` |
| Iterating a web app role in compose mode | `i8-iterate-compose` |
| Iterating a web app role in swarm mode | `i8-iterate-swarm` |
| Validating every role across both modes, compose then swarm | `i8-iterate-roundtrip` |
| Iterating on `svc-runner` or the self-hosted runner infrastructure | `i8-iterate-runner` |
| Iterating on a GitHub Actions workflow | `i8-iterate-workflow` |
| Writing or updating a Playwright spec for a `web-*` role | `i8-iterate-playwright` |
| Bringing UI roles into the corporate design, role by role from the design queue | `i8-designer` |
| Screenshotting the deployed roles after a green iteration and filing design proposals into the design queue | `i8-tune-design` |
| Running or validating tests for a specific scope | `i8-test` |
| Running the quality gate (`make quality`) to green in the shared test runner, without a deploy stack | `i8-quality` |
| Running the full gate (`make quality-high`: quality plus every lint) to green in the shared test runner, without a deploy stack | `i8-quality-high` |
| Cleaning up code, docs, or roles after a change | `i8-refactor` |
| Making CI, a deploy or a gate faster without giving up coverage | `i8-tune-velocity` |
| Splitting an over-budget CI row into variants that keep its coverage | `i8-variant-split` |
| Inspecting the variant tree one CI row really deploys | `i8-variant-tree` |
| Checking a branch out into a parallel worktree | `i8-worktree-create` |
| Releasing a parallel worktree, its own deploy stack and its slot, while the infra runner and the shared test runners keep running | `i8-worktree-down` |
| Freeing disk space and `/tmp` that agents filled: toolchain images through `make build-cleanup`, cache space through `make cache-evict`, and the list of stale test runners and of held and orphaned pool job stacks | `i8-cleanup` |
| A GitHub Actions / CI run failed and needs triage | `triage` |
| A local deploy is failing on the host | `i8-debug-local` |
| Inspecting a `*.log` or `*job-logs.txt` file dropped in the workdir | `i8-debug-log` |
| Pulling a sibling feature branch and merging it into the current one | `i8-merge-sibling` |
| Staged changes are ready to be committed | `i8-commit` |
| A branch is ready to be opened as a pull request | `i8-pull-request` |
| Pushing a branch through the manual-CI draft → ready-for-review cycle | `i8-push-trigger-pull` |
| Leading a CI run with a priority line that verifies the branch's open questions | `i8-ci-trigger-priority` |
| Verifying from both ends at once: the CI run on a triage loop plus local iteration | `i8-verify-parallel` |
| Writing every announcement of a release from one brief | `i8-release` |
| Writing a release's changelog entry on deterministic version jumps and contributors | `i8-release-changelog` |
| Writing the blog article and banner of a release | `i8-release-article` |
| Writing the LinkedIn article and post of a release | `i8-release-linkedin` |
| Writing the Mastodon post of a release | `i8-release-mastodon` |
| Writing the WhatsApp channel post and personal message of a release | `i8-release-whatsapp` |
| Writing the investor, customer and developer newsletters of a release | `i8-release-newsletter` |
| Writing the Instagram image and caption of a release | `i8-release-instagram` |
| Writing a new requirement | `i8-requirement-create` |
| Implementing an existing requirement file end to end | `i8-requirement-implement` |
| A GitHub Actions / CI run failed and needs a grouped, root-caused fix plan | `i8-debug-ci` |
| Reviewing the whole project for legal soundness: licences, attribution, data protection, trademarks | `i8-advocate` |
| Authoring or updating a role-local `javascript.js` for browser integration | `i8-file-role-javascript` |
| Authoring or updating a role-local `style.css` for role theming | `i8-file-role-style` |
| Authoring or updating a role-local `playwright.spec.js` | `i8-file-role-playwright-spec` |
| Authoring or updating a role-local `playwright.env.j2` | `i8-file-role-playwright-env` |
| Handling Ansible `group_vars` application defaults via the applications lookup | `i8-file-group-vars` |
