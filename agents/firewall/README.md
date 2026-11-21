# agents/firewall/

The RBAC agent firewall: what an agent may do, over which channels, apps, MCP
tools, accounts and egress hosts.

## Rule syntax

A rule is `Kind(target):actions`.

- `Kind` is one of `channel`, `app`, `mcp`, `account`, `egress`.
- `target` is `name` or `name/resource`; it may hold `${VAR}` references to
  the deploy variables listed in `variables.yml`.
- `actions` is `crud` (all four), `none`, or a `+`-joined subset of `create`,
  `read`, `update`, `delete`. `egress` carries no actions.

## Evaluation

`deny` beats `ask` beats `allow`, and a request that matches no rule is denied.
A role composes others through `includes`.

A role's `settings` names a Claude Code settings file relative to the
repository root. Each entry of the file's `permissions` `allow`, `ask` and
`deny` lists joins that verdict as a `tool` rule, kept verbatim and matched only
by its exact text. The managed settings carry only `tool` rules, and the write
gate drops every `tool` allow and ask rule of an agent that may not write. The
`interactive` role takes [.claude/settings.json](../../.claude/settings.json), the
permission SPOT of the root [AGENTS.md](../../AGENTS.md).

## Kinds in `roles.yml`

The five kinds cover every grant written in `roles.yml`:

- forge and workspace operations are `app(<forge-or-workspace>/<operation>)`,
  for example `app(fork/push):create`, `app(github/pull_request):create`,
  `app(workspace/worktree):crud`;
- reachable hosts are `egress(<host>)`, denied by default;
- chat rooms are `channel(<role>/<room>)`;
- MCP tools are `mcp(<server>/<tool>)`;
- external identities are `account(<provider>/<label>)`.

## Providers

`github`, `gitea` and `gitlab` are built in. Any other external service is
declared once under [providers/](providers/README.md) with its base URL and API flavour, and is
then usable as `account(<provider>/<label>)`.

## Compilation

The compiler lowers these roles into the per-caller policy of
`svc-ai-mcp-adapter`, the container egress allowlist, the agent account's
LDAP groups, the agent workspace's read-only managed settings, and the channel
account's room memberships. `vm_egress_proxy` computes the refuse and admit
lists of a hypervisor-side egress proxy in front of an agent VM, including the
MCP adapter, the agent's forks, the model gateway in gateway mode and the
pinned resolver; no deploy calls it yet.

## Accounts and repositories

An `account` grant is active while `agents.<role>.credentials` holds a
non-empty entry under its `<provider>/<label>` key or the provisioner holds a
record for it; the first active grant is the default account. A
`repositories` entry is `<owner>/<name>`, worked through the default account,
or `<provider>/<label>:<owner>/<name>`, worked through the named account; a
repository the list does not name is refused. See
[accounts.py](../../utils/agents/accounts.py).

## Overrides

An override folds onto a resolved role through `narrow` only: it may add
`deny` rules, and `ask` rules on a target a base `allow` grants verbatim; any
other rule or key could widen a verdict and is refused.
