# 110 - Proxmox Test Target and Pool Token per Workspace

## User Story

As the operator of a platform that provisions customer servers on Proxmox VE, I want `web-app-proxmox` to deploy a real Proxmox VE as the store's test target and to give each workspace a resource pool with a privilege-separated token scoped to it, so that the store's Proxmox lane runs against the real API and a workspace's credential can touch only the VMs of its own pool.

## Background

The store's requirement 062 (`infinito-nexus/gui: docs/requirements/062-slim-store-orders-provisioned-through-platform-roles.md`, decisions 14 and 18, criteria 062:136 and 062:192) needs this core side. [093 - Agents: VM Workspaces on Incus and Proxmox](093-agents-vm-workspaces.md) built the role for agent VMs; its host criteria for the broker's pool and token are still open.

### Today

- `web-app-proxmox` runs Proxmox VE as one Docker container built from the official repository (`roles/web-app-proxmox/README.md:9`).
- The deploy refuses a host that also runs `web-app-keycloak`, `svc-ai-litellm` or `web-app-openbao` (`roles/web-app-proxmox/vars/main.yml:18-22`) unless `services.proxmox.shared_host` is true (`roles/web-app-proxmox/tasks/00_core.yml:4-14`, `vars/main.yml:13`). The default is false (`roles/web-app-proxmox/meta/services.yml:46`), as `README.md:15` documents.
- The container has no user namespace of its own, so root in it is root on the host (`README.md:39`).
- The README documents one privilege-separated broker token per instance, bound to one pool (`README.md:48-58`). No task creates a pool or a token: the role's code holds no `pveum pool`, `pveum user token` or pool API call.
- Secrets reach the container on stdin and never on an argv (`README.md:22`), and break-glass access is `pveum` as root inside the container (`README.md:66`).

### Upstream

| Fact | Source |
| --- | --- |
| A privilege-separated API token has only the permissions granted to the token itself, never more than its user. | [Proxmox VE user management](https://pve.proxmox.com/wiki/User_Management) |
| A resource pool groups VMs and storage. A permission on `/pool/<id>` covers its members. | [Proxmox VE user management](https://pve.proxmox.com/wiki/User_Management) |
| Bridges and SDN zones are permission paths of their own (`/sdn/zones/<zone>/<vnet>`). A VM NIC needs `SDN.Use` there, and without `SDN.Audit` or `SDN.Use` the bridge is not visible to the token. | [Proxmox VE user management](https://pve.proxmox.com/wiki/User_Management) |
| The `bpg/proxmox` provider needs SSH to the node only for snippets (custom cloud-init files), `source_file` uploads and `idmap`. VM creation and change, `import_from` and `download_file` use the API alone. | [bpg/proxmox provider](https://search.opentofu.org/provider/bpg/proxmox/latest) |

## Decisions

1. **A pool and a token per workspace.** `workspace apply` (102) creates, through `pveum` inside the container (the role's break-glass path):
   - the pool `ws-<id>`;
   - the user `ws-<id>@pve` without a password;
   - a privilege-separated token `ws-<id>@pve!provision`;
   - its ACLs: the role `InfinitoWorkspace` on `/pool/ws-<id>`, `Datastore.AllocateSpace` and `Datastore.Audit` on the workspace's storage only, and `SDN.Use` on the workspace's bridge only.

   `InfinitoWorkspace` holds the VM privileges the `proxmox` root module of 104 needs to create, configure, start, stop and delete a VM: CPU, memory, disk, network, cloud-init and options, but no `Sys.*`, no `Permissions.*` and no privilege outside the pool. The README lists them, and a test pins the list. The token secret goes to `tenant/data/ws-<id>-provision/proxmox` (105) and nowhere else. `destroy` refuses while the pool holds a VM, and otherwise removes the token, the user and the pool.
2. **API only.** The workspace token gets no SSH access to the node, so the `proxmox` root module uses no snippet, no `source_file` and no `idmap`. Cloud-init stays with what the API sets: user, keys, network and DNS. So Proxmox returns no `host_key` in the provision output, and the first contact pins the host key (104 decision 4, store decision 17).
3. **The test target.** The store's Proxmox lane uses a real Proxmox VE that this role deploys, never a fake (store decision 18). Where it runs is the open decision below. The criteria hold for every option.

## Open Decision: Where the Proxmox Test Target Runs

Store decision 18 places it on echoserver, which runs Keycloak and OpenBao. So the role refuses the host unless `services.proxmox.shared_host` is true.

| Option | What it means | Risk |
| --- | --- | --- |
| A | A host of its own, for example a small dedicated server that runs only `web-app-proxmox`. | None shared: a compromise of Proxmox VE or a QEMU escape from a test VM reaches only that host. Costs one server. |
| B | A virtual machine on echoserver, in a platform project of `svc-virt-incus` (109), as an inventory host of its own with nested virtualization. The role's refusal does not trigger, because the VM is another host. | A compromise stops at the VM boundary. It needs nested KVM on echoserver, and VMs inside run slower. |
| C | `services.proxmox.shared_host: true` on echoserver. The risk is written into the inventory next to the flag and into the README. | Root in the Proxmox container is root on echoserver (`README.md:39`). A compromise of Proxmox VE, whose API the store's tests drive, or a QEMU escape from a test VM, reaches Keycloak, OpenBao and every secret they hold. |

Recommendation: **A**, the most secure option. If no second host is available, B. C only with the operator accepting the written risk.

## Acceptance Criteria

### Pool and token

- [ ] `workspace apply` creates the pool `ws-<id>`, the user `ws-<id>@pve`, the privilege-separated token and its ACLs. A second `apply` changes nothing and keeps the token (`proxmox workspaces: apply creates pool, user, token and ACLs once` in `roles/web-app-proxmox/files/playwright/test-workspace-pools.js`).
- [ ] `InfinitoWorkspace` holds exactly the privileges the README lists, none of `Sys.*` or `Permissions.*` among them. A negative control adds `Sys.Modify` and must fail (`test_the_workspace_role_holds_exactly_its_privileges` in `tests/unit/python/roles/web-app-proxmox/test_workspace_role.py`).
- [ ] With the token of workspace A, the `proxmox` root module of 104 creates, starts, stops and deletes a VM in pool `ws-<A>` on A's bridge and storage (`provision: proxmox creates and destroys a server` in `roles/web-app-semaphore/files/playwright/test-provision.js`).
- [ ] With the same token, each of these is refused: reading or changing a VM of pool `ws-<B>` or of the broker's pool, creating a VM outside `ws-<A>`, putting a NIC on another bridge, adding a disk on another storage, any `/nodes/<node>/` system call, and any `/access/` write (`proxmox workspaces: a token reaches only its own pool` in `test-workspace-pools.js`).
- [ ] The token secret is in OpenBao at `tenant/data/ws-<id>-provision/proxmox`. No file on the host and no line of the deploy log holds it (`proxmox workspaces: the token secret exists only in OpenBao` in `test-workspace-pools.js`).
- [ ] `workspace destroy` refuses while the pool holds a VM, and otherwise leaves neither the token, the user nor the pool (`proxmox workspaces: destroy removes token, user and pool` in `test-workspace-pools.js`).
- [ ] After a container restart, every workspace pool, user and token is unchanged (`proxmox workspaces: a restart keeps every pool and token` in `test-workspace-pools.js`).

### API only

- [ ] The `proxmox` root module declares no `ssh` block, no snippet, no `source_file` and no `idmap` (`test_the_proxmox_root_needs_no_node_ssh` in `tests/lint/repository/opentofu/test_root_modules.py`).

### Test target

- [ ] The test target deploys at the place the operator picked. Under C, the deploy passes only with `services.proxmox.shared_host: true` and the written risk present in the inventory; under A and B, the refusal of `00_core.yml:4-14` stays untouched (`test_shared_host_needs_its_written_risk` in `tests/unit/python/roles/web-app-proxmox/test_shared_host.py`).
- [ ] The store's Proxmox lane reaches the target with a workspace token over TLS that it verifies, never with certificate checks off, and runs a provision and a destroy there (`provision: proxmox creates and destroys a server` in `test-provision.js`, from the store's e2e stack).

### Documentation

- [ ] The [README](../../roles/web-app-proxmox/README.md) documents the workspace pools and tokens with the exact privileges, the API-only rule and the test target the operator picked, with its risk (`test_the_readme_names_the_workspace_pools` in `tests/unit/python/roles/web-app-proxmox/test_readme.py`).
