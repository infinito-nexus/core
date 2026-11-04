# 079 - Agents Phase 2: Tooling Gaps

## User Story

As an operator, I want every make target the routine tool nodes need to exist and every defect the running agents reported in existing targets to be fixed, so that the routines of the agents restructuring call deterministic tooling instead of working around it.

## Scope

- Phase 2 of [089 - Agents and AI Restructuring](089-agents-restructuring.md). The Tooling gaps section of 089 lists the targets and defects the criteria below refer to.
- Builds on: the make targets that already exist (`ci-wait`, `test-ref`, `i18n-load`, `i18n-pause`, `i18n-resume`, `legal-inventory`, `legal-probe`, `design-gallery`) and the routine tool nodes of [078](078-agents-phase-1-foundations.md).
- Gate: every criterion is proven by its own run of the target on a local development stack, recorded in `agents/criteria.yml`.
- Depends on: no other phase; it MAY be implemented in parallel to phase 1.

## Acceptance Criteria

### Tooling gaps

- [ ] Each make target listed under Tooling gaps exists, is documented in `make help` and is called by the routine that needs it.
- [ ] The lint for one role or one file reports a key-order error in `default.env` and a prefix-group error in a handler file name within one minute, without the full gate.
- [ ] The affected-roles resolver keeps a pull request that only adds a test under `tests/` at its real matrix instead of `__ALL__`.
- [ ] `make compose-role-sync task=<task> pw=<args>` runs the spec.
- [ ] `make compose-playwright` runs the current spec and `.env`.
- [ ] `make design-palette sync=role` re-renders `.env`.
- [ ] `make compose-deploy mode=update` finds the inventory written by `make roundtrip` without an explicit `variant`.
- [ ] Gallery screenshots land in the run directory, not in the host `/tmp`.
- [ ] The install stamp stays valid after a commit hook run.
- [ ] `make quality-high` installs every lint tool before the parallel lint dispatch, and ten parallel runs show no import race.
- [ ] The quality gate reports a lint failure in a new untracked file.
- [ ] npm installs succeed inside the sandbox.
- [ ] The slot picker refuses a slot whose subnet a leftover network still holds.
- [ ] `agents/skills/` holds a rule for writing escapes in code (`\U0000XXXX` or `\N{NAME}`, never `\uXXXX` through the Edit or Write tool), and a lint flags private-use or surrogate characters in source files.
- [ ] A routine fetch succeeds when a fork tag is clobbered.

### Lint tests

- [ ] Every lint of the catalog runs alone through the lint target for one role or one file.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
