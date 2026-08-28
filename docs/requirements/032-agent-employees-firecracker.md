# 032 - Kernel-Isolated AI Agent Employees with Flowise Supervisor

## User Story

As a platform administrator of Infinito.Nexus, I want to deploy self-hostable AI agent platforms (Hermes Agent, OpenClaw) as kernel-isolated, scalable "employees" across my nodes, coordinated by a Flowise supervisor over MCP and routed to models through the [031](031-llm-gateway-model-backends.md) gateway, so that I run a fleet of isolated agents with cross-agent pipelines and kernel-level isolation, without bespoke per-agent wiring.

## Background

The agents are real, self-hostable, open-source platforms, each deployed as its own role:

- **[Hermes Agent](https://hermes-agent.nousresearch.com/)** (Nous Research, MIT). Self-hostable with `local`, `Docker`, `SSH`, `Singularity`, `Modal` backends plus container hardening. Ships an official web dashboard with **self-hosted OIDC** auth (fits the platform SSO), delegates work through **isolated subagents**, has persistent memory, scheduling, vision web browsing, and MCP support (**client since v0.2.0, server since v0.6.0**). Deployed as `web-app-hermes`.
- **[OpenClaw](https://openclaw.ai/)** (open-source, npm/pnpm). Built-in Gateway web dashboard (default port `18789`) plus CLI/TUI, browser control, filesystem sandbox, persistent memory, skills/plugins, and native MCP (`@modelcontextprotocol/sdk`, both client and server). Deployed as `web-app-openclaw`.

Both bring their own agent logic and internal sandboxing. This requirement adds the **isolation and scaling substrate** around them plus a **Flowise supervisor** for cross-agent coordination. Model routing is the [031](031-llm-gateway-model-backends.md) gateway; the MCP tool contract is [025](025-mcp-role-integration.md).

Both platforms run model-generated code, which is untrusted, so a kernel-level boundary is required on top of their in-app sandboxing. [gVisor](https://gvisor.dev/) provides that boundary behind an OCI runtime, so each agent app stays a normal container spec and only pins `runtime: runsc`, reusing the existing image pipeline, replicas, healthchecks, and dual-mode machinery. [Kata Containers](https://katacontainers.io/) wrapping Firecracker was the original choice; Decision #2 records why it is unreachable on this container engine. ([E2B](https://github.com/e2b-dev/infra) is the higher-level alternative but brings its own Nomad/Consul orchestration and x86-cloud self-host, which would replace the swarm model.)

Two host- and swarm-level facts constrain the design and are settled below: swarm's stack deploy drops the compose `runtime:` key, so the runtime has to become a node-wide default, and every deploy path in this repository runs inside a privileged container, so a hypervisor-backed runtime cannot be exercised here at all.

## Confirmed Decisions

These choices are settled at requirement creation time and bound the implementation. Re-opening any of them MUST be recorded in the implementing PR.

1. **Each agent platform is its own role; no generic wrapper.** `web-app-hermes` and `web-app-openclaw` are separate roles reflecting their different stacks (Hermes Docker backend vs OpenClaw npm/pnpm). No speculative "generic agent runner" abstraction. Additional agent platforms become additional roles.
2. **Isolation is gVisor on top of in-app sandboxing; Firecracker is out of reach on this engine.** Each agent app runs under `runtime: runsc`, a userspace guest kernel that intercepts syscalls before they reach the host, so untrusted model-generated code stays kernel-isolated even if the app's own sandbox is bypassed. No custom VMM, jailer wiring, or bespoke rootfs pipeline. E2B/Beam noted as alternatives in the role README but not adopted.

   Kata with the Firecracker hypervisor was the original choice and cannot be delivered on Docker Engine: Firecracker requires the container rootfs as a block device (the containerd `devmapper` snapshotter), while dockerd always hands the runtime a directory. Kata's Firecracker driver advertises no filesystem sharing, and Kata's own documentation tests Docker with QEMU as the VMM. Reaching a microVM here means moving the agent tier off dockerd onto containerd with `devmapper`, which is a separate decision. Until then the microVM clauses below describe an intent, not a shipped mechanism.

   No agent needs host access to do agent work: OpenClaw's browser control and filesystem access run inside the guest, and Hermes' subagent execution runs inside the guest, so the agent runtime is fully isolatable. The only host-level demand is Hermes' web dashboard, which wants `network_mode: host` and a shared host PID namespace solely to display **host** metrics that an isolated guest cannot expose. That host-monitoring view is severable and MUST NOT pull the agent tier out of its isolated runtime: the agent runtime stays isolated, and the host-metrics dashboard is either run in Hermes' embedded/in-process mode (with reduced host stats) or split out to a separate non-isolated `runc` sidecar.
3. **Swarm parity via node-default runtime.** `docker stack deploy` ignores the compose `runtime:` key. The isolating runtime is therefore installed and set as the daemon-wide default on placement-labelled agent nodes; the agent services are pinned there via placement constraint, and every other service is kept off those nodes by the inverse constraint, because a node-wide default runtime applies to whatever is scheduled on it. Compose mode uses the compose `runtime:` key directly on the same image. Both modes MUST reach a running isolated agent, and the deploy MUST refuse to label a node whose daemon still defaults to the shared kernel. A dedicated provisioning role (`svc-virt-kata`) installs the runtime, re-renders the daemon configuration, and labels the node.
4. **Never a plain container, and the deploy proves it.** A preflight probes the host for `/dev/kvm` and for each runtime's binary, and selects the strongest runtime that is actually installed; the choice is logged at deploy time. It MUST NOT fall back to a plain `runc` container: unisolated execution of model-generated code is never allowed.

   This is the one clause that carries a hard guarantee, so it is enforced rather than asserted. In compose the agent role reads the runtime the container actually received and refuses the deploy when it is `runc`. In swarm the node reads its own default runtime and refuses the sandbox label while that is still `runc`, because the label is what routes sandboxed services to it. A lint additionally refuses a privileged container, a host network, pid, ipc or user namespace, and a host docker socket in any role that declares the sandbox, since any one of those hands the workload back to the host and cancels the runtime.

   The embodied deployment of [034](034-svc-ai-robot.md) is the deliberate exception: it drops the runtime because a guest kernel between the agent and the hardware it drives defeats the purpose, and it narrows the grant to an explicit device allowlist instead.
5. **Raspberry Pi is a real deploy target.** Agent images MUST publish an `arm64` manifest so a Pi-class node can pull them, and the agents MUST schedule across at least two labelled worker nodes. This is arch coverage, not arch exclusivity: the same images keep running on the amd64 nodes that CI and the lab use, so the requirement is that every architecture a node may have is published, never that a deploy is pinned to one.
6. **Models go through the [031](031-llm-gateway-model-backends.md) gateway.** Each agent's BYO-model config points only at the `svc-ai-litellm` `/v1` + a model alias; it never addresses a provider directly. The Pis run no large models locally; heavy inference is routed to a GPU/external backend by the gateway.
7. **Agents consume tools as MCP clients via the [025](025-mcp-role-integration.md) mechanism.** Hermes and OpenClaw are configured as MCP clients of the repository's MCP server roles over HTTP/SSE (not stdio: under microVM isolation and multi-node placement a stdio subprocess cannot reach an MCP server in another container). Discovery and credentials reuse 025's [`roles_with_service`](../../plugins/lookup/roles_with_service.py) lookup and `credentials:` blocks. Both roles are added to 025's MCP audit as client roles. Only 025's shared contract (the `services.mcp` schema) and the lookup extension are prerequisites for this requirement; 025's audit tooling, full lint set, and baserow+openwebui slice are independent later work.
8. **Flowise cross-agent supervisor is Phase 2, deferred.** The supervisor (Flowise as MCP client delegating to Hermes' MCP-server mode v0.6.0+ and OpenClaw's MCP-server, chaining cross-agent pipelines) is a separate later slice, not the first implementation. Rationale: it depends on the young hermes MCP-server mode and adds a second orchestration tier. The first slice ships each agent standalone; the supervisor design below is retained as the Phase 2 target. Single-agent use MUST always work without Flowise.
9. **Agent dashboards are public behind proxy + Keycloak OIDC.** `web-app-hermes` and `web-app-openclaw` follow the standard `web-app-*` contract: own canonical domain, reverse-proxy routing, SSO enforced via [`web-app-keycloak`](../../roles/web-app-keycloak/). Hermes uses its native self-hosted OIDC support. OpenClaw's native OIDC is unverified upstream: if absent, the dashboard sits behind the platform's standard auth-proxy pattern (SSO enforced at the proxy, OpenClaw's own token auth staying internal-only). No unauthenticated public surface either way.

   Amended after implementation: the deployed Hermes version serves a bearer API rather than a browser dashboard, so its native-OIDC support cannot be used. It is gated at the auth proxy instead, like OpenClaw and Flowise, admitting the role's `administrator` and `mcp` groups. Holding `API_SERVER_KEY` alone was the whole boundary before, which put every MCP provider Hermes is admitted to behind one shared deployment secret. The cost of the proxy is deliberate: an OpenAI-compatible client presenting only a bearer no longer reaches Hermes through its public vhost, and has to come from inside the container network.
10. **First slice is dashboard-only.** The first implementation wires each agent through its web dashboard only. Chat-platform connectors (Telegram/Discord/Signal/...), which need operator-supplied bot tokens, are deferred to a follow-up and MUST NOT block the first green deploy.
11. **Agents that spin up containers use nested Docker inside the isolated runtime; host socket passthrough is forbidden.** When an agent needs to run compose workloads (see the scenario below), it runs a nested Docker daemon inside its own isolated runtime. Mounting the host `/var/run/docker.sock` into an agent that executes model-generated code is **forbidden**: it grants root-equivalent host control and defeats the isolation entirely. Nested Docker costs performance and, on gVisor, may need `runsc` with the appropriate platform; the role README MUST document the overhead. An agent role that requires containers MUST declare this capability explicitly.
12. **Embodied / dedicated-device mode moves the trust boundary to the whole device.** For an agent that owns and explores a single-purpose machine (a robot platform, a home-assistant appliance), the isolation boundary is the entire dedicated node, not a guest kernel inside it. Privileged/full host access (`/dev`, GPIO, sensors, cameras, host network) is allowed **only** on a node that is dedicated, single-tenant, network-segmented, and explicitly opted in, with the blast radius documented in the role README. It is **forbidden on any shared cluster node**: agents on shared infrastructure always stay under Decision #4. This is the deliberate exception that keeps the general rule intact rather than a hole in it.
13. **An agent can be provisioned with its own platform user account.** Creating an agent employee optionally provisions a dedicated identity through the platform's existing user mechanism (the `users` lookup, LDAP via [`svc-db-openldap`](../../roles/svc-db-openldap/), SSO via [`web-app-keycloak`](../../roles/web-app-keycloak/)); no new account system is built. The account is a **non-privileged standard user** by default (never administrator/service-account-with-mutating-tools). When enabled, the agent authenticates as its own user: OIDC login to its dashboard, a distinct mailbox/identity, and MCP calls made with `auth_subject: user` ([025](025-mcp-role-integration.md)) scoped to that account rather than a shared service account. The account is opt-in per agent; its password/token lives in the role's `meta/secrets.yml` `credentials:` block, never in README or env. An agent MUST also be deployable against an existing account (no forced account creation).

## Architecture

```mermaid
flowchart TB
    operator([Operator]) -->|"supervise / build pipeline"| flowise
    operator -.->|"direct chat (Telegram/Discord/CLI)"| pool

    subgraph host["Swarm cluster"]
        subgraph mgr["Manager / normal-runtime nodes (runc)"]
            flowise["web-app-flowise<br/>supervisor (MCP client)"]
            gw["svc-ai-litellm<br/>LLM gateway /v1 (031)"]
        end

        subgraph anode["Agent nodes (label: kata-capable, arm64)"]
            k["container engine + gVisor runtime"]
            subgraph pool["Agent employees (swarm replicas)"]
                hermes["web-app-hermes<br/>gVisor isolated<br/>MCP client+server"]
                openclaw["web-app-openclaw<br/>gVisor isolated<br/>MCP client+server"]
            end
            k --- pool
        end
    end

    mcpservers["025 MCP server roles<br/>(nextcloud, gitlab, baserow...)"]

    flowise -->|"delegate via MCP"| hermes
    flowise -->|"delegate via MCP"| openclaw
    hermes & openclaw -->|"tools via MCP (025)"| mcpservers
    flowise & hermes & openclaw -->|"models /v1"| gw

    kvm["/dev/kvm + nested virt"]:::pre --> anode
    classDef pre fill:#fdd,stroke:#c00,stroke-dasharray: 4 3;
```

## Flowise Supervisor (cross-agent pipelines) — Phase 2

Deferred to a follow-up slice (Decision #8). Flowise treats each agent as an MCP-exposed sub-agent and chains them. Single-agent use always works directly, without Flowise. Retained here as the Phase 2 target.

```mermaid
sequenceDiagram
    actor User
    participant F as Flowise supervisor
    participant O as web-app-openclaw
    participant H as web-app-hermes
    participant G as svc-ai-litellm /v1

    User->>F: "research topic X, then schedule a summary call"
    F->>O: MCP: browse + gather (openclaw tools)
    O->>G: inference /v1
    O-->>F: research result
    F->>H: MCP: schedule + notify (hermes tools)
    H->>G: inference /v1
    H-->>F: scheduled + sent
    F-->>User: combined result
```

## Example Scenario (orientation): corporate-design CSS sweep agent

A concrete end-to-end illustration of how the pieces compose. Nothing here is a new mechanism; it maps onto the decisions above.

**Admin sets it up once:**

1. Deploy an agent employee (`web-app-hermes` or `web-app-openclaw`) with its **own non-privileged account** (Decision #13) provisioned via `users`/LDAP/Keycloak, plus a matching account on the git forge ([`web-app-gitea`](../../roles/web-app-gitea/) / [`web-app-gitlab`](../../roles/web-app-gitlab/)).
2. Grant it three tool surfaces: the git-forge **MCP server** (025) for branches/PRs/review comments, a **local-deploy/exec** capability inside its isolated sandbox (to `make compose-deploy` a role and drive a browser), and its **model alias** via the 031 gateway.
3. Give it the task prompt: "iterate every role, align its CSS to the corporate design, screenshot, open a PR, wait for review".

**The agent then runs autonomously, step by step:**

```mermaid
sequenceDiagram
    actor Admin
    participant A as Agent employee<br/>(own account, isolated runtime)
    participant S as Local sandbox<br/>(compose + browser)
    participant G as svc-ai-litellm /v1 (031)
    participant F as git forge MCP (025)

    Admin->>A: create agent + assign task
    loop for each role under roles/
        A->>S: make compose-deploy <role> (spin up local containers)
        A->>S: open app, capture 12 screenshots
        A->>G: assess screenshots vs corporate design
        G-->>A: inconsistencies + CSS fixes
        A->>S: edit role CSS/theme, redeploy, re-screenshot
        A->>A: commit on a per-sweep branch
    end
    A->>F: open PR (as its own account) with screenshots
    A->>F: poll PR for review feedback
    F-->>A: reviewer comments
    A->>F: push fixes, update PR
    Note over A,F: waits / iterates until approved
```

Key points this scenario pins down:

- **"Spins up local containers"** happens inside the agent's isolated sandbox, which MUST therefore be able to run compose workloads (nested Docker inside the isolated runtime). This is a real capability constraint the agent role MUST declare; it is exactly the kind of host-near need Decision #4's runtime selection has to accommodate.
- **"Created its own account"** = the git-forge identity from Decision #13; the PR is authored by the agent, not a shared bot.
- **"Waits for feedback"** = the agent polls the PR through the git-forge MCP server (025); the human review gate stays human.
- Models, tools, and identity are the three separate planes (031 gateway, 025 MCP, IAM account) meeting in one workflow.

## Example Scenario (orientation): Hermes as an isolated home assistant on a Raspberry Pi

Formalised as its own role in [033-web-app-homeassistant.md](033-web-app-homeassistant.md). Hermes runs on a single Raspberry Pi as a household assistant, kernel-isolated, reachable over voice/chat, controlling home devices through MCP without ever getting host access.

**Setup:**

1. One Pi joins as a `kata-capable` arm64 node; `web-app-hermes` deploys there under the isolating runtime selected by the preflight (Decision #4).
2. Models route through the 031 gateway: light intents to a small local `svc-ai-ollama`, heavy reasoning to an external backend.
3. Home devices are reached as **MCP tool servers** (025) over HTTP/SSE, e.g. a smart-home hub MCP server. Hermes is an MCP client only; it never touches the Pi host.
4. The dashboard sits behind proxy + Keycloak OIDC (Decision #9); voice/chat connectors are the follow-up (Decision #10).

```mermaid
flowchart LR
    user([Household]) -->|voice / chat| hermes
    subgraph pi["Raspberry Pi (kata-capable, arm64)"]
        hermes["web-app-hermes<br/>gVisor isolated"]
    end
    gw["svc-ai-litellm /v1 (031)"]
    hub["smart-home hub<br/>MCP server (025)"]
    hermes -->|models /v1| gw
    hermes -->|"devices via MCP (tools)"| hub
```

The point: an assistant with real reach into the home, but the agent runtime stays isolated and the Pi host stays untouched. Capabilities come through MCP tools, not host access.

## Example Scenario (orientation): Hermes as an embodied robot platform (full-access, dedicated device)

The inverse of every other scenario, and deliberately so. Formalised as its own role in [034-svc-ai-robot.md](034-svc-ai-robot.md). Here Hermes is given full rights to explore and drive **one dedicated machine** so it can map its own hardware and act in the physical world: the robot platform idea. This is only coherent under Decision #12.

**Setup:**

1. A **dedicated, single-tenant, network-segmented** device (robot controller / SBC), NOT a shared cluster node. This device is Hermes' body.
2. `web-app-hermes` is deployed there with privileged host access (`/dev`, GPIO, sensors, cameras, host network). The trust boundary is the whole device (Decision #12), so there is no microVM around the agent here.
3. Hermes self-explores: enumerates devices, probes sensors/actuators, maps what the machine can do, then controls it. Models via the 031 gateway; higher-level tools still via MCP (025) where useful.
4. Explicit operator opt-in; the README documents the blast radius (this agent can do anything the device can).

```mermaid
flowchart TB
    subgraph device["Dedicated device = the trust boundary (Decision #12)"]
        hermes["web-app-hermes<br/>PRIVILEGED, full host access"]
        hw["/dev, GPIO, sensors,<br/>cameras, actuators"]
        hermes -->|explore + control| hw
    end
    gw["svc-ai-litellm /v1 (031)"]
    hermes -->|models /v1| gw

    shared["Shared cluster nodes"]:::no
    device -. "network-segmented, NEVER on shared infra" .-> shared
    classDef no fill:#fdd,stroke:#c00,stroke-dasharray:4 3;
```

Guardrails that keep this from becoming a hole in the isolation model:

- **Dedicated device only.** Full access is permitted solely on a node whose only tenant is this agent. Forbidden on any shared cluster node (Decision #12).
- **Segmentation.** The device is network-isolated from shared infrastructure; a compromise stays on the device.
- **Explicit, documented opt-in.** Privileged mode is off by default and the README states exactly what the agent can reach.
- **Different class, not a downgrade.** This is embodied-agent deployment, not the shared-infra agent tier relaxing its rules; shared-infra agents stay isolated per Decision #4.

## Use Cases

```mermaid
flowchart LR
    operator([Operator])
    admin([Platform admin])

    subgraph sys["Agent fleet"]
        u1(["Deploy agent employee (hermes / openclaw)"])
        u1b(["Provision agent's own user account (opt-in)"])
        u2(["Chat / assign task directly"])
        u3(["Build cross-agent pipeline in Flowise"])
        u4(["Deploy stack + preflight KVM"])
        u5(["Scale agent replicas"])
        u6(["Connect MCP tool servers (025)"])
    end

    operator --- u2
    operator --- u3
    admin --- u1
    u1 -.->|opt-in| u1b
    admin --- u4
    admin --- u5
    admin --- u6
```

## Multi-Node Deployment (Raspberry Pi cluster)

Each Raspberry Pi joins the swarm as an agent node labelled `kata-capable` with the isolating runtime as its daemon-wide default (Decision #3, applied per node). Flowise and the gateway run on a manager node. Swarm distributes agent replicas across the Pis; adding a Pi adds agent capacity with no code change. The Pis do **not** run large models locally: agents speak only the gateway `/v1`, which routes light work to a small local `svc-ai-ollama` and heavy work to a GPU or external backend. All node-run images MUST be `arm64`.

```mermaid
flowchart TB
    operator([Operator]) -->|supervise| flowise
    admin([Admin]) -->|"docker node update --label-add"| swarm

    subgraph swarm["Docker Swarm cluster"]
        subgraph mgr["Manager node (runc)"]
            flowise["web-app-flowise"]
            gw["svc-ai-litellm gateway /v1"]
        end
        subgraph pi1["Raspberry Pi #1 (kata-default, arm64)"]
            h1["web-app-hermes<br/>gVisor isolated"]
        end
        subgraph pi2["Raspberry Pi #2 (kata-default, arm64)"]
            o1["web-app-openclaw<br/>gVisor isolated"]
        end
        subgraph piN["Raspberry Pi #N ..."]
            aN["agent replica ..."]
        end
    end

    flowise -->|delegate MCP| h1
    flowise -->|delegate MCP| o1
    h1 & o1 & aN -->|only /v1| gw
```

## Where each guarantee is enforced

| Guarantee | Enforced by |
| --- | --- |
| Isolation is real in compose | `svc-virt-kata/tasks/utils/assert_isolated.yml` reads `HostConfig.Runtime` off the running container and refuses `runc` |
| Isolation is real in swarm | `svc-virt-kata/tasks/00_core.yml` reads `container info --format DefaultRuntime` and refuses `runc` **before** labelling the node, so the label never promises what the node cannot deliver |
| The sandbox cannot be escaped through the host daemon | [test_sandboxed_no_host_socket.py](../../tests/lint/ansible/services/test_sandboxed_no_host_socket.py), scoped to the roles whose templates pin `SANDBOX_RUNTIME` |
| Inference reaches only the gateway | [test_litellm_consumer_contract.py](../../tests/lint/ansible/services/test_litellm_consumer_contract.py) and [test_model_backend_via_gateway.py](../../tests/lint/ansible/jinja/test_model_backend_via_gateway.py) |
| The dashboards are gated | `test-oidc-login.js` and `test-guest.js` in each agent's `files/playwright/` |
| The agent images run on arm64 | [test_arm64_images.py](../../tests/external/update/docker/test_arm64_images.py) |

## Agent identity

The platform already reserves a user key per role, so `hermes` and `openclaw` existed as accounts, non-privileged and each with its own mailbox, before either role claimed one. Claiming the key is what turns a reservation into an identity the agent may authenticate as, and gives the account its description.

Each agent now claims its own key in `meta/users.yml` and declares nothing about the password there, because provisioning stores one for every declared account. An earlier attempt pinned the password to a separate `identity_password` credential in `meta/secrets.yml`; that was the wrong home for it. An account password belongs to the account, and the provisioning code says so directly: a role whose registration rejects the shell-safe alphabet states that in its own `meta/users.yml` rather than carrying a second credential beside the account it already owns. The `{{ 42 | strong_password }}` that re-renders per read is the fallback for an inventory nobody provisioned, not the value a deployed account holds.

Pointing an agent at an account that already exists needs no code: the inventory `users` variable overrides the same key, which is the documented override path.

[test_agent_identity.py](../../tests/lint/ansible/services/test_agent_identity.py) holds the claim, the absence of any role on the account, and the absence of a second credential for it, over the roles derived from the sandbox-runtime scan rather than a list.

Still open: MCP calls carrying that identity. Every server role issues one shared `service_account` token today, so `auth_subject: user` has nothing to resolve against until 035 introduces per-user credentials.

## Blocked on hardware and on Phase 2

A single-node lab cannot answer the multi-node criteria: replica scaling, placement across two `kata-capable` Raspberry-Pi-class nodes, and the compose-plus-swarm end-to-end pass all need the cluster the requirement describes. The arm64 half of the placement criterion is proven by the image check above; the two-node half is not.

The Flowise supervisor criteria are Phase 2 and untouched: neither agent runs in MCP-server mode yet.

## Acceptance Criteria

- [x] A `web-app-hermes` role deploys Hermes Agent and it comes up healthy with at least one connected interface.
- [ ] A `web-app-openclaw` role deploys OpenClaw and it comes up healthy with at least one connected interface.
- [x] Both agent dashboards are exposed behind the reverse proxy with Keycloak OIDC SSO; no unauthenticated public surface.
- [x] Both agent roles run under the isolating runtime, and the deploy fails when they do not: compose reads the container's actual runtime, swarm reads the node's default runtime before labelling it.
- [x] Where KVM is unavailable (e.g. local `act` through DinD), the agent runs under the gVisor (`runsc`) fallback, never plain `runc`; the chosen runtime is logged at deploy time.
- [x] The agent runtime stays isolated; any host-metrics dashboard is either embedded or a separate `runc` sidecar and does not force the agent tier out of the isolated runtime.
- [x] A preflight probes `/dev/kvm` and each runtime binary, selects the strongest one installed, and logs the choice with an actionable line.
- [x] The first slice is dashboard-only; no chat-platform connector is required for a green deploy.
- [ ] Agent count scales up and down by changing swarm replicas.
- [ ] Agents run on `arm64` and are scheduled across at least two `kata-capable` nodes (Raspberry Pi class); joining an additional labelled node adds capacity without a code change.
- [x] Both agents reach inference only through the [031](031-llm-gateway-model-backends.md) gateway (BYO-model config points at `/v1`); switching a backend is a gateway config change, no agent redeploy.
- [ ] Each agent is configured as an MCP client of at least one [025](025-mcp-role-integration.md) MCP server role over HTTP/SSE, and a tool call through that server succeeds; both roles are added to 025's MCP audit.
- [ ] Creating an agent optionally provisions a dedicated platform user account via the existing `users`/LDAP/Keycloak mechanism; the agent authenticates as that account (OIDC dashboard login, MCP `auth_subject: user`), and deploying against an existing account instead also works. **Partly done:** the account half is implemented and linted (see [Agent identity](#agent-identity)); the MCP half waits on the per-user credential model that [035](035-mcp-proxy-expansion.md) still owns.
- [x] An agent that runs container workloads does so via a nested Docker daemon inside its isolated runtime; no agent mounts the host `/var/run/docker.sock`. Neither agent runs container workloads today, so the enforceable half is the socket ban, held by `tests/lint/ansible/services/test_sandboxed_no_host_socket.py`; wiring a nested daemon is due with the first agent that needs one.
- [ ] (Phase 2) Hermes' and OpenClaw's MCP-server mode is enabled; Flowise connects to both as MCP clients and delegates a task to each.
- [ ] (Phase 2) A Flowise supervisor flow runs a cross-agent pipeline that hands a result from one agent to the other and returns a combined output; single-agent use still works without Flowise.
- [ ] Compose mode brings up an isolated agent via the compose `runtime:` key; swarm mode brings up an isolated agent via the node-default runtime on a placement-labelled node. Both modes are green end to end.
- [x] Each agent role ships a Playwright spec exercising its deployed surface, and both are green.

## Cross-linking

- Implementing PR: _to be linked_.

## See Also

- Model plane (LLM gateway) this depends on: [031-llm-gateway-model-backends.md](031-llm-gateway-model-backends.md)
- MCP tool plane: [025-mcp-role-integration.md](025-mcp-role-integration.md)
- Hermes Agent: [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/)
- OpenClaw: [openclaw.ai](https://openclaw.ai/)
- Firecracker sandbox reference: [E2B infra](https://github.com/e2b-dev/infra)
