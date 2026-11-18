# 109 - Incus API Listener and Project per Workspace

## User Story

As the operator of a platform that sells demo and cloud servers on its own Incus host, I want `svc-virt-incus` to offer its API over HTTPS to the provision runner only, and to give each workspace a restricted project reached with a certificate scoped to that project, so that a workspace's credential can create and destroy only its own instances and the store's e2e stack runs against real Incus.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decisions 12, 14 and 18, criteria 062:85, 062:136 and 062:192) needs this core side. [093 - Agents: VM Workspaces on Incus and Proxmox](093-agents-vm-workspaces.md) built the role for agent VMs; this requirement adds customer workspaces beside them.

### Today

- `svc-virt-incus` runs in host mode only (`roles/svc-virt-incus/meta/services.yml`) and is `pre-alpha` (`services.yml`).
- It proves `/dev/kvm` (`roles/svc-virt-incus/tasks/00_core.yml`), starts the daemon through `incus.socket` (`00_core.yml`) and talks to it over the local socket `/var/lib/incus/unix.socket` (`00_core.yml`).
- Its preseed creates the bridge `agentbr0` without NAT and the storage pool, and sets no `core.https_address` (`roles/svc-virt-incus/vars/main.yml`). So the API is not reachable over the network.
- It creates and reconciles one restricted project `agents-<domain>` (`vars/main.yml`, `00_core.yml`).
- The dev stack's `target` service is a privileged systemd container (`compose.yml`), so it sees `/dev/kvm` when the host has one.

### Upstream

| Fact | Source |
| --- | --- |
| `core.https_address` opens the REST API on an address and port, 8443 by convention. | [Incus server configuration](https://linuxcontainers.org/incus/docs/main/server_config/) |
| A client is trusted by its certificate. `incus config trust add` issues a single-use join token, which `core.remote_token_expiry` lets expire. `incus config trust add-certificate` adds a certificate directly. | [Incus remote API authentication](https://linuxcontainers.org/incus/docs/main/authentication/) |
| A trust entry with `restricted` true reaches only the projects it lists, and an empty list means none. It cannot change server configuration, nor the limits and restrictions of its projects. | [Incus remote API authentication](https://linuxcontainers.org/incus/docs/main/authentication/) |
| Project restrictions cover privileged containers, nesting, host-path disks, NICs, network access and low-level VM options; limits cover instances, CPU, memory and disk. `limits.containers` 0 allows virtual machines only. | [Incus project configuration](https://linuxcontainers.org/incus/docs/main/reference/projects/) |

## Decisions

1. **An HTTPS listener behind the host firewall.** `services.incus.api.enabled` (default `false`) sets `core.https_address` to `services.incus.api.listen`, an address and port 8443. Through `svc-net-firewall`, the role's own nftables table admits that port only from `services.incus.api.allowed_sources`: the egress addresses of the platform's provision runner, and of the e2e stack in a test deployment. The deploy stores the fields `endpoint`, `certificate` and `fingerprint` of the server in OpenBao at `platform/data/provision/incus-<host>` (105). The provision runner takes `endpoint` as `INCUS_ADDR` and pins `certificate` (`roles/web-app-semaphore/files/opentofu/credentials.json`). No client trusts the server blindly.
2. **A restricted certificate per workspace, no token on the wire.** `workspace apply` (102) creates the project `ws-<id>`. On the platform runner, inside its task, it generates a client key pair and writes the private key to `tenant/data/ws-<id>-provision/incus`. It adds the certificate over the local socket with `incus config trust add-certificate --restricted --projects ws-<id>`. The private key never reaches the Incus host, and no join token for a workspace exists. Join tokens stay for enrolling other clients by hand. `core.remote_token_expiry` is `1h`, so an unused one dies.
3. **Virtual machines only.** A workspace project carries the restrictions of the agents project and adds `limits.containers` 0, together with the limits of the workspace's plan. Echoserver also runs Keycloak and OpenBao (store item 9), and a container shares the host kernel with them, while a virtual machine has its own.
4. **A network per workspace.** Each workspace project gets its own bridge. The host firewall forwards nothing between two workspace bridges or between a workspace bridge and `agentbr0`. Decision 7 makes a workspace instance reachable from outside.
5. **The e2e target.** Variant 0 deploys `svc-virt-incus` with the API on into the dev stack's `target` container. The store's e2e stack then reaches real Incus with a workspace certificate. Like production, the target needs `/dev/kvm`. On a host without it, the lane stops with a message naming the missing device and counts as not run.
6. **Echoserver.** The inventory of echoserver turns `services.incus.api.enabled` on. The role keeps refusing a host without `/dev/kvm` or without a copy-on-write pool.
7. **Public addresses from a routed subnet (operator pick A, 2026-11-13).** Demo and cloud instances need an address the deploy runner reaches over SSH and a customer reaches over HTTPS. The hosting provider routes a public IPv4 and IPv6 subnet to the Incus host, and `services.incus.workspaces.subnet.ipv4` and `.ipv6` name them. `workspace apply` gives each workspace bridge its own slice of both, with `ipv4.nat` and `ipv6.nat` false, and the bridge hands each instance its own addresses from that slice. The host routes the addresses and holds no NAT and no port forward for a workspace instance. Each instance NIC sets `security.ipv4_filtering` and `security.ipv6_filtering`, so an instance cannot send from an address that is not its own ([Incus NIC devices](https://linuxcontainers.org/incus/docs/main/reference/devices_nic/)). With workspaces on and either subnet unset, the deploy refuses to run. The dev stack routes the documentation ranges `198.51.100.0/24` and `2001:db8:62::/48` to `target` as its subnet.

Rejected:

- IPv6 only from echoserver's prefix with IPv4 through Incus network forwards on echoserver's address (option B): IPv4 users reach an instance only on forwarded ports, and 443 can be forwarded to one instance only.
- One shared TLS passthrough proxy on echoserver (option C): every instance would depend on one proxy shared between workspaces.

## Acceptance Criteria

### API listener

- [ ] With `services.incus.api.enabled` on, `incus config get core.https_address` returns `services.incus.api.listen`. With it off, the key is empty (`test_the_listener_follows_its_switch` in `tests/unit/python/roles/svc-virt-incus/test_api_listener.py`; `incus api: the listener answers on 8443` in `roles/svc-virt-incus/files/playwright/test-workspace-projects.js`). Partly met: `test_the_listener_follows_its_switch` and its control hold against `INCUS_SERVER_CONFIG` and the reconcile tasks of `roles/svc-virt-incus/tasks/00_core.yml`; the spec is not written, live proof in the roundtrip.
- [ ] The role's nftables table admits port 8443 only from `services.incus.api.allowed_sources`. A connection from another address of the dev stack is dropped (`test_the_firewall_admits_only_the_allowed_sources` in `test_api_listener.py`; `incus api: an address off the list is dropped` in `test-workspace-projects.js`). Partly met: `test_the_firewall_admits_only_the_allowed_sources` evaluates the rendered `roles/svc-virt-incus/templates/nftables.conf.j2` per packet, and a control without the IPv6 rule fails; the spec is live proof in the roundtrip.
- [ ] The server certificate's fingerprint is in OpenBao after the deploy, and a client that presents the wrong server fingerprint stops before it sends a request (`incus api: the provision runner pins the server certificate` in `test-workspace-projects.js`).
- [x] `core.remote_token_expiry` is `1h` (`test_join_tokens_expire` in `test_api_listener.py`). Met: `services.incus.remote_token_expiry` is `1h` and `INCUS_SERVER_CONFIG` reconciles it with the listener.

### Workspace projects

- [ ] `workspace apply` creates the project `ws-<id>` with the restrictions of the agents project, `limits.containers` 0 and the plan's limits, and a trust entry that is restricted to `ws-<id>` alone. A second `apply` changes nothing (`incus workspaces: apply creates a restricted project and certificate once` in `test-workspace-projects.js`).
- [ ] With the certificate of workspace A, the spec creates and deletes a virtual machine in `ws-<A>`. It is refused on each of these: listing or creating instances in `ws-<B>` or in `agents-<domain>`, creating a container, creating a privileged instance, attaching a host-path disk, setting `limits.instances` of `ws-<A>`, and setting any server key (`incus workspaces: a certificate reaches only its own project` in `test-workspace-projects.js`).
- [ ] The private key of a workspace certificate exists only in OpenBao: no file on the Incus host holds it, and the trust store holds no pending join token for a workspace (`incus workspaces: no private key and no token on the host` in `test-workspace-projects.js`). Partly met: `test_the_private_key_reaches_openbao_only` in `tests/unit/python/roles/svc-virt-incus/test_workspace_certificate.py` generates a real key pair with the task's argv and proves only the certificate reaches the Incus host, with controls for a key on stdin and an unrestricted entry; the spec is live proof in the roundtrip.
- [ ] An instance on the bridge of `ws-<A>` reaches neither an instance on the bridge of `ws-<B>` nor an agent VM on `agentbr0` (`incus workspaces: workspace bridges are isolated` in `test-workspace-projects.js`).
- [ ] `workspace destroy` refuses while the project holds an instance, and otherwise removes the project, its bridge and its trust entry (`incus workspaces: destroy removes project, bridge and certificate` in `test-workspace-projects.js`).

### Public addresses

- [x] A rendered workspace bridge holds a slice of `services.incus.workspaces.subnet.ipv4` and `.ipv6`, with `ipv4.nat` and `ipv6.nat` false, and the host holds no NAT rule and no network forward for it. With workspaces on and either subnet unset, the deploy fails before it creates a project (`test_workspace_bridges_route_public_addresses` and `test_the_deploy_refuses_workspaces_without_a_subnet` in `tests/unit/python/roles/svc-virt-incus/test_workspace_network.py`). Met: both tests, `test_negative_control_a_nat_bridge_is_caught` and `test_negative_control_a_guard_without_the_ipv6_check_is_caught`; the slice comes from `incus_workspace_network` in `roles/svc-virt-incus/filter_plugins/incus_workspace.py`, the guard is `🛑 Refuse workspaces without a routed subnet` in `tasks/00_core.yml`.
- [ ] A virtual machine of workspace A answers SSH on its own IPv4 and IPv6 address from outside the host, and on no address of the host (`incus workspaces: an instance answers on its own addresses` in `test-workspace-projects.js`).
- [ ] A packet the instance sends from an address that is not its own is dropped (`incus workspaces: a spoofed source address is dropped` in `test-workspace-projects.js`).

### e2e target and echoserver

- [ ] Variant 0 of `svc-virt-incus` deploys into the dev stack's `target` with the API on, and the `incus` root module of 104 provisions and destroys a virtual machine there (`provision: incus creates and destroys a server` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
- [x] On a host without `/dev/kvm`, the e2e lane stops with a message naming the device, and the run reports it as not run (`test_the_lane_stops_without_kvm` in `tests/unit/python/roles/svc-virt-incus/test_e2e_target.py`). Met: `test_the_lane_stops_without_kvm` and its control `test_the_lane_runs_with_kvm` drive the deploy handler of `cli/administration/deploy/development/deploy/cli.py` with the role's own `requires_devices` from `roles/svc-virt-incus/meta/services.yml`; `decline` in `cli/administration/deploy/development/deploy/devices.py` prints the declined verdict naming the device and writes the **not run** line to the job summary. The role keeps its refusal (`test_kvm_is_required` in `tests/unit/python/roles/svc-virt-incus/test_incus_role.py`).
- [ ] Echoserver's inventory turns the API on, and a deploy there passes every criterion of this section (the deploy log and the spec's `✓` lines from the echoserver run).

### Documentation

- [x] The [README](../../roles/svc-virt-incus/README.md) documents the listener, its firewall sources, the workspace projects and certificates, the VM-only rule and the routed subnet with its slices (`roles/svc-virt-incus/README.md`).
