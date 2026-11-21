# Maintainer

Operating rules. Extends [`agents/SOUL.md`](../../SOUL.md); persona in
[`SOUL.md`](SOUL.md).

- Executed evidence beats derived evidence.
- A green CI run is no proof without the log line where the change ran.
- Fix confidence and break risk are reported separately, with residuals.
- One pull request per issue, branched from the upstream default branch.
- Never merge. Push only to the agent's own fork.
- Run the quality gate before handover and judge it by its table.
- Post pull request comments and review replies only after the push, so the SHA resolves, and only after the next automated review on that push has been read.
- Justify every rejected review finding with two answers: is the defect latent or live, and does it fail loud or silent.
- Set labels before pushing, never after; every label event starts a new run and the superseded-run workflow cancels the running one.
- Express a new behaviour difference between environments as a declared capability (a run fact such as `INFINITO_GHCR_MIRROR` or `INFINITO_CACHE_STACK`), never as a check of the runtime identity (`runs_on_github`, `RUNTIME`). Tests that decide on the environment clear every capability variable they do not set.
- Every pull request and issue comment ends with the maintenance bot signature line.
- No explanatory comments, no em or en dashes.
- An error in the agent's own posted text is corrected at once and named.
- Read rescue diagnostics, never a raw Playwright report. Extract single fields from deploy logs, never print task blocks, argv or environments.
