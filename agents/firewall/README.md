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

## Kinds in `roles.yml`

The five kinds cover every grant:

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
`svc-ai-mcp-adapter`, the container egress allowlist, the agent account's LDAP
groups, the agent workspace's read-only managed settings, and the channel
account's room memberships.
