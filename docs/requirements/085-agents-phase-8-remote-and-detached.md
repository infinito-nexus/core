# 085 - Agents Phase 8: Remote Board and Detached Instances

## User Story

As an operator, I want a throwaway instance on a developer's machine to run the agents against the board, accounts and storage of a remote live instance, so that developers work with real agents without holding an admin token of the live instance and without losing state at a teardown.

## Scope

- Phase 8 of [089 - Agents and AI Restructuring](089-agents-restructuring.md), phase 5 of its iteration plan. The Remote board and detached instances section of 089 applies.
- Builds on: `utils/orchestrator/instance_api.py`, `utils/agents/redact.py`, the provisioner's lease, renew, reaper and audit ingest in `roles/svc-ai-agent-provisioner`, and the orchestrator poller.
- Gate: the remote scenarios against a second local instance through `make agents-verify` are green.
- Depends on: [084](084-agents-phase-7-roles-at-work.md).

## Acceptance Criteria

### Security controls

- [ ] With the live instance unreachable, a throwaway instance makes no claim, board write, push or channel post (probe recorded).

### Remote board and detached instances

- [ ] With the board pointing to the remote OpenProject, an assignment to a role group there starts that role's agent on the throwaway instance through polling within two poll intervals.
- [ ] Every agent acts on every remote provider as `<role code>0<instance id>`, visible in the remote applications' logs.
- [ ] A throwaway instance registers its name with its public key; a second registration of the same name with another key is refused, and the same key takes over.
- [ ] A provisioning request authenticated with the developer's login creates the agents' accounts on the live instance after approval, sets the developer as `owner`, and no admin token of the live instance exists on the developer machine (probe recorded).
- [ ] The broker reaches the OpenProject API with an OIDC JWT bearer token and Nextcloud with an app password created from the agent's login; neither appears inside a workspace (probe recorded).
- [ ] Gitea and GitLab tokens minted by the broker are short-lived and never appear inside a workspace (probe recorded).
- [ ] The Matrix channel adapter logs in with login credentials, keeps its session outside the workspace, and after a teardown and redeploy decrypts earlier end-to-end encrypted room history through key backup, with the recovery key read from the inventory or OpenBao.
- [ ] After a teardown, login credentials, the Matrix recovery key and the instance key are still available from the agent's `.kdbx` on the live Nextcloud, opened with the master key from the inventory or OpenBao, and nothing of them is kept only in `sys-token-store`.
- [ ] With OpenBao enabled, an instance's AppRole reads `agents/<instance id>/*` and is refused everywhere else.
- [ ] Two throwaway instances claiming the same work package at once end with exactly one owner; the other gets `409` and moves on.
- [ ] A claim is refused when the work package is not `Approved` or not assigned to the agent's role group, and OpenProject refuses an agent account's transition outside `Approved` -> `In progress` -> `Review`.
- [ ] When an instance's lease expires, the live reaper revokes its tokens, app passwords and Matrix devices and returns its claimed work packages to `Approved`; a write from the instance after expiry is refused.
- [ ] `make agents-stop` suspends without revoking, and `make agents-start` resumes; a teardown revokes.
- [ ] No agent writes to the board directly; board writes come from the orchestrator, and each agent's egress to remote hosts matches its own `account` grants exactly.
- [ ] After a teardown and redeploy, every agent's harness home and `.kdbx` are restored from the latest Nextcloud snapshot.
- [ ] The whole harness home, session transcripts included, reaches the agent's Nextcloud with every seeded secret redacted in the uploaded copy, the `.kdbx` arrives encrypted, and the owner can restore an earlier snapshot.
- [ ] An agent without a Nextcloud grant uploads nothing.
- [ ] Snapshots are uploaded at routine checkpoints and at teardown by the sidecar, never continuously from open files.
- [ ] Audit entries of a throwaway instance reach the live instance with server-assigned time, sequence and hash chain; a dropped entry is reported as a gap, and a teardown waits until the spool is empty.
- [ ] A GitHub push from a throwaway instance uses that instance's own token and signing key under the role account, carries the instance id in the branch name, and revoking that token leaves other instances working.
- [ ] A channel with credentials for a remote instance carries agent messages there; without them the local channel is used.

## Cross-linking

- Index: [089 - Agents and AI Restructuring](089-agents-restructuring.md).
- Implementing PR: to be added.
