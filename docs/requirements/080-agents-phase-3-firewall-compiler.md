# 080 - Agents Phase 3: Firewall Compiler

## User Story

As an operator, I want the agent firewall compiler to turn the `allow`, `ask` and `deny` rules of `agents/firewall/` into proven decisions and generated settings, so that every surface the control plane deploys later receives limits that unit tests have already checked.

## Scope

- Phase 3 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), phase 2 of its iteration plan. The Agent firewall and Safety controls sections of 089 define the rules and grants.
- Builds on: `agents/firewall/` (roles, variables, providers), `utils/firewall/parse.py`, `utils/firewall/compile.py` and the lints L08 to L12.
- Gate: the compiler unit tests and the firewall lints are green; the generated managed settings are probed in a single `web-app-workspace` deploy.
- Depends on: [078](078-agents-phase-1-foundations.md).

## Acceptance Criteria

### Routines

- [ ] An `ask` hit outside a declared gate node is reported as a firewall misconfiguration.

### Forges and external accounts

- [ ] An external provider declared in `agents/firewall/providers/` is usable in an `account` grant, and a grant naming an undeclared provider fails the lint.

### Agent firewall

- [ ] A unit test proves `deny` beats `ask` beats `allow` and that an unmatched request is denied.
- [ ] A rule target with `${VAR}` expands from the deploy variables, and the `make i18n-translate` lane address is granted that way.
- [ ] The workspace's `/etc/claude-code/managed-settings.json` is generated from the agent's grants, owned by root, read-only, and the agent process runs as a non-root user that cannot change it (probe recorded).
- [ ] `agents/firewall/` ships every baseline role of the design table with the grants listed there.
- [ ] The root `AGENTS.md` permission rules for interactive sessions are expressed by the `interactive` firewall role, and `.claude/settings.json` is generated from it.

### Security controls

- [ ] A node that reads untrusted content runs without an agent runtime and without tools, and only its schema output reaches tool-using nodes (unit test).
- [ ] With `write_enabled: false`, or with a failed deny, kill-switch, audit or identity scenario, the compiler emits no write grant for the agent.
- [ ] The lint flags an `app` grant that maps to a privileged group.

### Profile catalog

- [ ] A started agent's effective rights equal the intersection of the profile's grants and its owner's rights (unit test over the compiler).

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
