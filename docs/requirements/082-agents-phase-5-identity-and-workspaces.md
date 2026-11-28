# 082 - Agents Phase 5: Identity, Credentials, Models, Workspaces and Forges

## User Story

As an operator, I want every agent to act under its own account with its own credentials, model key and model list, to work in an isolated workspace and to reach the forges only through its own accounts, so that each agent's reach is bounded by its grants and traceable to it.

## Scope

- Phase 5 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), the second part of phase 3 of its iteration plan. The Identity and credentials, Account naming, Model selection, Forge working model, Workspaces, Agent firewall and Safety controls sections of 089 apply.
- Builds on: `utils/agents/` (accounts, keepass, naming, budget), `roles/svc-ai-agent-provisioner`, `roles/svc-ai-litellm`, `roles/svc-ai-s1`, `roles/svc-ai-mcp-adapter`, `roles/web-app-workspace`, `roles/dsk-agentbox`, `roles/dsk-code` and the compiled firewall of [080](080-agents-phase-3-firewall-compiler.md).
- Gate: single-role deploys with in-container probes and the phase's scenarios through `make agents-verify` are green.
- Depends on: [081](081-agents-phase-4-control-plane.md).

## Acceptance Criteria

### Identity and credentials

- [ ] Every team agent and every user-started agent has its own LDAP account with an `owner` attribute.
- [ ] Every agent logs in by SSO to an app its firewall grants, and is refused by an app it does not grant.
- [ ] Every agent has its own LiteLLM virtual key, and the gateway logs show spend per agent key.
- [ ] Claude Code in a workspace completes a request through the gateway's Anthropic upstream, once with `auth: api_key` and once with `auth: subscription`.
- [ ] No agent workspace or agent container holds a model provider credential (probe recorded).
  - Exception: a VM workspace in login mode holds its agent's vendor login, see [093](093-agents-vm-workspaces.md).
- [x] A `github` account grant without credentials in the inventory is inactive, and the next active account is the default.
  - Evidence: `available_accounts` in `utils/agents/accounts.py` derives the active grants from `agents.<role>.credentials`, the shipped roles in `agents/firewall/roles.yml` grant `account(github/<role>)` before Gitea and GitLab; proven by `TestAvailableAccounts` in `tests/unit/python/utils/agents/test_accounts.py`, including the inventory override through `lookup('agent_config')`.
- [ ] Overriding a credential under `agents.<role>.credentials` in the inventory replaces the generated default.
- [ ] Every agent credential lives in the agent's `.kdbx`; a grep over `sys-token-store` and the inventory finds no agent credential except the master key and the bootstrap credentials.
- [ ] With a Nextcloud grant the `.kdbx` is stored in the agent's Nextcloud account; without one it stays in the agent's persistent volume.
- [ ] In `keepass.mode: broker` the agent never reads the master key and receives only the entries the broker releases (probe recorded); in `keepass.mode: agent`, set in the inventory, the agent opens the database itself.

### Forges and external accounts

- [ ] A team agent with a manually supplied GitHub token forks `infinito-nexus/core` into its account, pushes a signed commit to a branch of the fork and opens a pull request against the upstream.
- [ ] The same flow works through a Gitea account and through a GitLab account of the platform, both created and keyed at deploy time.
- [ ] The first `account` grant is the agent's default account: a routine step without an explicit account uses it (unit test), and reordering the grants in the inventory switches the default on the next deploy.
  - Partial: `account_grants` in `utils/firewall/compile.py` with `default_account`, proven by `TestAccountGrants` in `tests/unit/python/utils/firewall/test_compile.py`. Live: reorder the grants in the inventory, redeploy and read the default account the agent uses.
- [x] A `repositories` entry that names an account is worked through that account instead of the default.
  - Evidence: `repository_entry`, `repository_accounts` and `worked_through` in `utils/agents/accounts.py` (entry `<provider>/<label>:<owner>/<name>`), lint L01 refuses a malformed entry or one naming an ungranted account; proven by `TestRepositoryAccounts` in `tests/unit/python/utils/agents/test_accounts.py` and `test_a_malformed_or_ungranted_repositories_entry_fails` in `tests/lint/agents/test_l01_agent_fields.py`.
- [ ] A push from an agent to the upstream remote is refused by the agent firewall.
  - Partial: `utils/agents/pre_push.py` refuses a push unless `decide` allows `app(<remote>/push):create` for the agent's firewall roles, proven as a `pre-push` hook against temporary bare remotes by `test_push_to_the_upstream_is_refused_and_nothing_lands` in `tests/unit/python/utils/agents/test_pre_push.py`. Open: the workspace installs the hook.
- [ ] A merge attempt by an agent is refused by the agent firewall.
- [ ] Setting `repositories` in the inventory makes the agent work on the listed repositories only.

### Workspaces

- [ ] `web-app-workspace` serves a browser IDE with the Claude Code extension installed, behind SSO, inside a Kata or gVisor sandbox.
- [ ] `dsk-agentbox` installs agentbox, and `dsk-gnt-claude`, `dsk-gnt-codex` and `dsk-gnt-pi` run inside an agentbox box.
- [ ] `dsk-code` installs `vscodium` when the local workspace is enabled, and attaches to the box.
- [ ] Inside either workspace, the host home, the host Docker socket and host credentials are not reachable (probe recorded).
- [ ] From inside a workspace, Docker commands reach the agent's own stack and are refused on a foreign stack.
- [ ] Nested Docker in either workspace builds an image without `--privileged`.
- [ ] Changing a reach-widening workspace key without the external approval blocks the workspace start.
- [ ] A human and an agent work in the same server workspace at the same time.

### Agent firewall

- [ ] A denied egress request is reported with its target within 10 seconds.
- [ ] `svc-ai-mcp-adapter` refuses an MCP tool call outside the agent's grants and returns the matched rule.
- [ ] The agent container cannot reach a host outside its `egress` grants (probe recorded).
- [ ] The agent account is member of exactly the LDAP groups derived from its `app` grants.
- [ ] No agent can write to `agents/firewall/` or to its overrides at runtime (probe recorded).

### Security controls

- [ ] In `keepass.mode: broker`, no file inside a workspace contains a long-lived credential, and git operations in the workspace succeed through the broker's credential helper and `ssh-agent` socket (probe recorded).
- [ ] A diff containing a seeded secret is stopped by the pre-push secret scan, and nothing reaches the remote.
  - Partial: the same hook scans the added lines of every unpushed commit with the patterns of `utils/agents/redact.py` and prints each hit masked, proven by `test_seeded_secret_is_refused_masked_and_nothing_lands` in `tests/unit/python/utils/agents/test_pre_push.py`. Open: the workspace installs the hook.
- [ ] Every agent authenticates to `svc-ai-mcp-adapter` with its own token; a token of one agent is refused for another, and the comparison is constant-time (unit test).
  - Partial: `authorize_client` in `roles/svc-ai-mcp-adapter/files/python/auth.py` compares through `hmac.compare_digest`, proven by `test_the_bearer_is_compared_in_constant_time` and `test_a_non_ascii_bearer_is_refused_not_raised` in `tests/unit/python/roles/svc-ai-mcp-adapter/files/test_auth.py`. Open: the adapter holds one bearer, not one token per agent.
- [ ] An MCP call to Gitea, GitLab, Zammad or Nextcloud reaches the application under the calling agent's own identity, visible in the application's log.
- [ ] Exceeding a quota in `agent.yml` stops the agent's next model call, tool call or forge write and reports the quota.
- [ ] A request for a model outside the agent's `models` list is refused by `svc-ai-litellm`, and `support`, `planner`, `operator` and user-started agents reach no external model by default.
- [ ] Within the allowed list, `svc-ai-s1` picks the model per request from the shared history in `infinito_decider`, and a grep finds no second sampler or history implementation.
- [ ] After a model is removed from an agent's `models` list, its earlier `agent_model_history` rows no longer influence the choice (unit test).
- [ ] Negative control for `judge_answers`: for prose, code, diff and structured replies, given one answering and one plainly non-answering reply, it picks the answering one; the result is recorded before the router uses its verdicts.

### Account naming

- [ ] An account of the agent form without a provisioner record is disabled and reported by the deploy and by the reaper (fixture account created through the admin console).
- [ ] An agent account of the longest form is accepted by every agent-reachable application (one scenario per application), and no agent gets a Bluesky account.

### Local setup and integration workflows

- [ ] Fork, push and pull request scenarios pass against the local `web-app-gitea`.
- [ ] Claude Code scenarios pass against the local model behind the gateway's Anthropic-protocol endpoint.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
