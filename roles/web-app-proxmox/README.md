# Proxmox VE

## Description

[Proxmox VE](https://www.proxmox.com/en/products/proxmox-virtual-environment/overview) is an open-source virtualization platform built on Debian. It runs QEMU/KVM virtual machines, manages their storage, networks and resource pools, and serves a web UI and a REST API with fine-grained, pool-scoped permissions and API tokens.

## Overview

This role runs a real Proxmox VE on any container host, in a data center or locally, as the hypervisor for agent VM workspaces and for the servers the store provisions per workspace. It ships two flavors, chosen by `services.proxmox.flavor`: `vm`, the default, boots Proxmox VE from the official installer as the guest of an unprivileged QEMU container, and `container` runs Proxmox VE itself in a container on a dedicated host. The web UI is served at its own domain through the front proxy, the agent broker (`svc-ai-agent-broker`) drives the agent VMs through a pool-scoped API token, and every workspace gets a resource pool with a privilege-separated token scoped to it.

## Flavors

`services.proxmox.flavor` takes `vm` or `container`, and the deploy refuses any other value. `meta/variants.yml` holds one row per flavor, so CI deploys both. Each flavor's steps live in `tasks/flavors/vm.yml` and `tasks/flavors/container.yml`; the realm, the RBAC sync, the templates, the workspace pools and tokens and the provision record are shared and run against whichever Proxmox VE the flavor started.

| | `vm` (default) | `container` |
| --- | --- | --- |
| Pin | `services.proxmox.ve.iso`: the installer ISO by file name and SHA-256 | `services.proxmox.ve.packages`: `pve-manager`, `pve-cluster`, `pve-qemu-kvm` and `qemu-server` at their versions |
| Image | Debian base, Debian's QEMU (`services.proxmox.launcher.packages`) and `proxmox-auto-install-assistant` (`services.proxmox.ve.installer`) at pinned versions | Debian base and the pinned packages of the official `pve-no-subscription` repository |
| Privileges | non-root UID, `/dev/kvm` only, every capability dropped, `no-new-privileges` | `/dev/kvm`, `/dev/net/tun`, `/dev/vhost-net`, `/dev/fuse`, `NET_ADMIN`, `SYS_ADMIN`, `cgroup: private` |
| Root in Proxmox VE | root in the guest only | root on the host |
| Co-hosting | runs beside `web-app-keycloak`, `svc-ai-litellm` and `web-app-openbao` | dedicated host only |

Both pins name the same Proxmox VE release, and a test holds them there. The image build refuses an empty keyring checksum and any unpinned package. There is no third-party image and no subscription workaround.

### Flavor `vm`

The role's container runs QEMU with KVM, which boots Proxmox VE as its guest. It needs a container engine and `/dev/kvm` only, so the role runs on Arch, on every distribution of the CI axis and inside the dev stack's `target`, with no host package and no host daemon.

- **Unprivileged launcher:** The container runs as the role's own UID and GID (its `group_id`), joins the group of `/dev/kvm`, holds `/dev/kvm` as its only device, drops every capability and sets `no-new-privileges`. A QEMU escape out of a VM inside Proxmox VE lands in the guest, and an escape out of the guest lands in an unprivileged container, so the co-hosting refusal does not run.
- **Network:** QEMU's user-mode network forwards the container's port 8006 to the guest's `pveproxy`, so the front proxy and the agent broker keep reaching `proxmox:8006`.
- **Guest channel:** The role runs its `pveum` and Perl steps, the RBAC sync and the template build inside the guest over SSH, through `pve-guest` in the container. The guest's SSH port is forwarded to `127.0.0.1:services.proxmox.guest.ssh_port` of the container only and published on no host address. The launcher pins the guest's host key, which it generated itself, and forwards only the `PROXMOX_*` variables, so a secret reaches the guest on no argv. Break-glass access takes the same path: `pve-guest pveum ...` inside the container.
- **Limits:** `services.proxmox.guest` sets the guest's vCPUs, memory and disk. The container's `cpus` and `mem_limit` hold the guest plus QEMU's overhead, and the capacity check measures the guest.

### Flavor `container`

The container runs Proxmox VE itself, so agent VMs run at full speed without nesting. Only this flavor renders the grants below, and only this flavor refuses a host that also runs `web-app-keycloak`, `svc-ai-litellm` or `web-app-openbao`, in its own groups or on another inventory host with the same address: root in this container is root on the host. The refusal has no override; move the role to a host of its own or deploy the `vm` flavor.

## Guest image

The `vm` guest is installed from the official installer, unattended, by the launcher on its first start:

1. It downloads `services.proxmox.ve.iso.file` from `services.proxmox.ve.iso.mirror` and refuses an ISO whose SHA-256 differs from `services.proxmox.ve.iso.sha256`.
2. It embeds core's answer file (`files/image/answer.toml`) with `proxmox-auto-install-assistant prepare-iso --fetch-from iso`, together with the first-boot hook (`files/shell/first-boot.sh`). The answer file sets `reboot-mode = "power-off"`, a `root-password-hashed` of a password the build discards, the reserved name `pve.example.invalid` and the hook, and holds no value of any deployment.
3. It boots the ISO under QEMU and KVM onto an empty disk and keeps the disk when the installer powers off, as `base-<tag>.qcow2` in the `proxmox_guest_base` volume. The tag is the digest of the ISO pin, the answer file and the hook.

Each deployment then boots a copy-on-write overlay on that base in the `proxmox_guest` volume. A guest keeps the release it was installed from; a deploy refuses a guest whose `pveversion` does not report the release of the ISO pin.

### First-boot values

The launcher hands the guest a QEMU `fw_cfg` item `opt/nexus.infinito.proxmox/first-boot` with its fully qualified name (`services.proxmox.guest.node` under `DOMAIN_PRIMARY`), a root password hash of a password nobody keeps, the launcher's SSH public key and an SSH host key it generated for this guest. On first boot the hook applies them, locks the root password (`usermod -L root`), regenerates the other SSH host keys, the machine id, the cluster CA, the node certificate and the ticket key, and only then admits the launcher's key. So no two deployments share a key. The guest's sshd keeps `UsePAM yes`, because without PAM it refuses a key login of a locked account, which would cut the guest channel.

Before it admits the key, the hook records what the guest booted with and what it made: SSH host key fingerprints, SHA-256 fingerprints of the node certificate and the cluster CA, and SHA-256 digests of the machine id and the root password hash, never a private key or a hash itself. The deploy reads that record over the guest channel, and the Playwright test `proxmox vm: no two deployments share a key` fails when a value of this deployment equals the image's, when the record is missing, or when the certificates Proxmox VE reports are not the ones the hook made. A guest installed before the hook kept the record carries none and fails that test until its `proxmox_guest` volume is recreated.

## Nested KVM

The launcher starts the guest with CPU type `host`. The deploy reads `nested` of the host's `kvm_intel` or `kvm_amd` and writes the result to the deploy log and to OpenBao at `platform/data/provision/proxmox-<host>`, beside the endpoint, the node, the storage, the bridge and the template ids. With nesting on, VMs inside Proxmox VE run with KVM; without it, as on GitHub-hosted runners, they run with `kvm: 0`: slower, same API. Under `container`, VMs always run on the host's KVM.

## API Listener

`services.proxmox.api.enabled` (default `false`) publishes `pveproxy` on port `services.proxmox.ports.public.api` (default `8606`, in the `api` band of `PORT_BANDS.public`) of the host address `services.proxmox.api.bind` (default `0.0.0.0`), beside the loopback port of the front proxy; with it off, the API is reached through the front proxy only, which refuses every API token (`templates/nginx/api_token_refusal.conf.j2`). The role's nftables table `infinito_web_app_proxmox` drops every connection to that port whose source is not in `services.proxmox.api.allowed_sources`: the egress addresses of the provision runner and, in a test deployment, of the e2e stack. An empty list admits no one, and an entry that is no address or network fails the deploy when the variables render. The table loads before the compose flush that publishes the port, so the listener is never open to every source, not even on a first deploy. Docker publishes the port through a DNAT rule that runs before the input hook, so the table filters in the prerouting hook at priority `-150`, ahead of that DNAT, and only packets addressed to the host itself (`fib daddr type local`), which leaves the front proxy's and the OAuth2 proxy's traffic to `proxmox:8006` on the container network untouched.

`pveproxy` serves a certificate of its own on that port: the deploy generates it inside the Proxmox VE the flavor runs (`files/shell/api-certificate.sh`) with `openssl req -x509`, one key per deployment that never leaves the node, and the subjectAltName of the name the consumers dial, and installs it with `pvenode cert set` as `/etc/pve/local/pveproxy-ssl.pem`. The stock node certificate names only the node, `localhost` and its addresses, while `bpg/proxmox` checks the dialled name against the certificate. A redeploy keeps a certificate that still names that host and outlives `PROXMOX_API_CERT_RENEW_SECONDS`, and replaces it otherwise. The deploy stores the fields `endpoint` (`https://<host>:<port>`), `certificate` and `fingerprint` (its SHA-256) in OpenBao at `platform/data/provision/proxmox-<host>`. As for `svc-virt-incus`, the endpoint is read inside containers, so a `<host>` in `NETWORK_LOOPBACK_HOSTS` is recorded as `host.docker.internal` and any other `<host>` as it stands. The provision runner takes `endpoint` as `PROXMOX_VE_ENDPOINT` and writes `certificate` to `servercerts/<host>.crt` of its task, which `SSL_CERT_DIR` names: `bpg/proxmox` `v0.119.0` has no CA option, so Go's system pool, which reads `SSL_CERT_DIR` beside the system bundle, is the one place a pin reaches it.

## Workspace templates

The deploy keeps two VM templates on the node, both from the pinned cloud image `services.proxmox.workspaces.image` (URL and SHA-256), each with a cloud-init drive on `services.proxmox.workspaces.storage` and no secret:

- `kvm`, id `services.proxmox.workspaces.templates.kvm` (default `9000`), with the VM option `kvm` 1;
- `emulated`, id `services.proxmox.workspaces.templates.emulated` (default `9001`), with `kvm` 0 and CPU type `qemu64`.

The template step checks the image's SHA-256 before the import. It keeps a template whose image digest is unchanged and replaces it otherwise, so a second deploy changes nothing. The template ids are shared with the default catalog of the `proxmox` root module of `web-app-semaphore`; a deployment that changes one changes the other. The root clones `templates.emulated` for a region whose `kvm` is false and `templates.kvm` otherwise, always as a full clone, so a template can be replaced without touching a VM cloned from it.

## Workspace pools and tokens

`workspace apply` (requirement 102) runs `tasks/workspace.yml` with `WORKSPACE` and `WORKSPACE_ACTION`. Through `pveum` inside the Proxmox VE the flavor runs, `apply` creates:

- the pool `ws-<id>`;
- the user `ws-<id>@pve` without a password;
- the privilege-separated token `ws-<id>@pve!provision`;
- the ACLs, for the user and its token alike, and no other ACL.

The roles and the paths they hold:

- `InfinitoWorkspace` on `/pool/ws-<id>`, propagated: `Pool.Audit`, `VM.Allocate`, `VM.Audit`, `VM.Config.CDROM`, `VM.Config.CPU`, `VM.Config.Cloudinit`, `VM.Config.Disk`, `VM.Config.HWType`, `VM.Config.Memory`, `VM.Config.Network`, `VM.Config.Options`, `VM.GuestAgent.Audit`, `VM.PowerMgmt`
- `InfinitoWorkspaceStorage` on `/storage/<services.proxmox.workspaces.storage>`: `Datastore.AllocateSpace`, `Datastore.Audit`
- `InfinitoWorkspaceBridge` on `/sdn/zones/localnetwork/<services.proxmox.workspaces.bridge>`: `SDN.Use`
- `InfinitoTemplateClone` on `/vms/<kvm id>` and `/vms/<emulated id>`: `VM.Clone`

No role holds a `Sys.*` or `Permissions.*` privilege. The clone-only right on the two templates is the one right outside the workspace's pool: it copies a template that holds no secret and neither changes, starts nor deletes it. A second `apply` changes nothing and keeps the token. The token secret goes to OpenBao at `tenant/data/ws-<id>-provision/proxmox` (fields `token_id`, the full token id `ws-<id>@pve!provision`, and `secret`; the provision runner joins them as `PROXMOX_VE_API_TOKEN` `<token_id>=<secret>`) and nowhere else; when OpenBao holds no secret of an existing token, `apply` issues the token anew. `destroy` refuses while the pool holds a VM, and otherwise removes the ACLs, the token, the user, the pool and the OpenBao key.

## API only

A workspace token gets no SSH access to the node, so the `proxmox` root module uses no snippet, no `source_file` and no `idmap`. Cloud-init stays with what the API sets: user, keys, network and DNS. Proxmox returns no host key in the provision output, so the first contact pins it.

## Features

- **Front proxy and group gate:** The UI is reached only through the front proxy on port 443, behind an OAuth2 proxy that admits only members of this role's administrator group. The SSO flags turn on as soon as any inventory host runs `web-app-keycloak`, and the deploy refuses to run while they resolve to false.
- **Hardware virtualization only:** Before the container starts, the deploy refuses a host without `/dev/kvm` and names the device; an amd64 CI runner without it fails the row instead of skipping it.
- **Sized limits:** The deploy refuses limits below the warm pool plus `agents.max_running` times the largest agent VM size plus `services.proxmox.agents.overhead`, and a host whose free memory or storage is below that demand plus `services.proxmox.agents.reserve`. On a redeploy the agent VMs of the resource pool `agents-<DOMAIN_PRIMARY>`, dots as dashes, count as free: the memory the running ones hold from the host's view (`memhost` of `pvesh get /cluster/resources`) and the space their volumes take on the node's local image storages (`used` of the storage content, and for LVM-thin, where Proxmox VE lists none, the data `lvs` reports). Before Proxmox VE runs, nothing is read and the check runs on the free memory and storage alone. Under `vm`, the agent disks live in the guest storage `services.proxmox.workspaces.storage`, a fixed pool that must hold the demand on its own, while the reserve stays with the host: its `total` and `used` come from `pvesh get /nodes/<node>/storage/<storage>/status`, and before the guest answers the whole `services.proxmox.guest.disk` stands in for it.
- **HTTPS upstream:** `pveproxy` speaks only HTTPS, so `services.proxmox.upstream_scheme: https` makes the front proxy location reach `127.0.0.1:7992` over TLS. The hop stays on the loopback, and nginx does not verify the self-signed `pveproxy` certificate. The OAuth2 proxy runs in `auth_request` mode and forwards no request to the upstream, so its `http://proxmox:8006` upstream entry carries no traffic.
- **OpenID realm:** The deploy converges the OpenID realm `services.proxmox.realm.id` against the shared Keycloak client: issuer, client id and secret, the username claim, user autocreation, and the realm as the default of the login window. A realm whose username claim differs is refused, because Proxmox VE fixes that claim at creation.
- **Administrator group:** The group `web-app-proxmox-administrator` holds the `Administrator` role on `/`, propagated. Proxmox VE accepts only `[A-Za-z0-9._-]` in an OpenID group claim, so the role cannot map the full-path RBAC claim; instead the RBAC sync (`tasks/utils/rbac/sync.yml`) adds every member of the Keycloak administrator group to it, at deploy and on its timer, and removes every other account from it.
- **Secret path:** The client secret reaches the container base64-encoded on the task's stdin and travels on as an environment variable named by `container exec -e`, so it is never on an argv. Proxmox VE stores it as `client-key` in `/etc/pve/domains.cfg`, where its own `pveum realm add` keeps it.
- **Content Security Policy:** `meta/csp.yml` allows `unsafe-eval` for Ext JS templates and inline scripts for the `index.html` that `pveproxy` renders with a per-request CSRF token.
- **No onion:** The deploy refuses to run while `services.tor.enabled` resolves to true, so the hypervisor UI never gets an onion address.
- **Compose only:** `meta/services.yml` enables compose mode and disables swarm, because the container owns the KVM device and the VM disks of one host.
- **Backup scope:** Under `vm`, the backup covers the guest overlay (`proxmox_guest`) with the Proxmox VE configuration, the templates and the VM disks inside it, and leaves out the base disks (`proxmox_guest_base`), which the launcher rebuilds. Under `container`, it covers the cluster configuration (`proxmox_config`) and the ISO and container templates (`proxmox_templates`), and leaves out `/var/lib/vz/images` (`proxmox_vm_disks`): the agent VM disks, which are destroyed when their task ends, and the base disks of the agent VM templates, which `make agents-vm-template` rebuilds.
- **Broker channel:** Secrets and tool calls reach an agent VM through the QEMU guest agent, and only after the broker assigned the VM to a task; never through cloud-init, the VM configuration or a snippet.

## Devices, capabilities and namespaces

The container runs without `privileged` in both flavors. Each grant in `templates/compose.yml.j2` and its reason:

- **`/dev/kvm`:** QEMU runs with hardware virtualization: the `vm` launcher boots the guest with it, and the `container` flavor starts the agent VMs with it.
- **`/dev/net/tun`:** `container` only; QEMU attaches each VM network card as a tap device on the VM bridge inside the container.
- **`/dev/vhost-net`:** `container` only; the in-kernel virtio network backend for those tap devices, so VM traffic is not copied through QEMU.
- **`/dev/fuse`:** `container` only; `pmxcfs` mounts the cluster file system at `/etc/pve` through FUSE; every Proxmox VE service reads its configuration there.
- **`NET_ADMIN`:** `container` only; creates the VM bridge `services.proxmox.vm_network.bridge`, its tap ports and the firewall rules that keep VM traffic on that bridge.
- **`SYS_ADMIN`:** `container` only; systemd mounts its own file systems and `pmxcfs` mounts `/etc/pve`.
- **`cgroup: private`:** `container` only; systemd and QEMU manage their own cgroup subtree, in the container's own cgroup namespace, not the host's.
- **Host namespaces:** none of network, PID or IPC; the container keeps its own. Under `container` it has no user namespace of its own unless the Docker daemon runs with `userns-remap`, so root in the container is root on the host.

The container publishes the web UI port 8006 as `127.0.0.1:7992` (`services.proxmox.ports.local.http`) for the front proxy and, with `services.proxmox.api.enabled` on, once more on `services.proxmox.api.bind` port `services.proxmox.ports.public.api` for the [API listener](#api-listener). Ports 3128, 111, 5405 and 22 are never published.

## Known gaps

- **Console websocket:** the noVNC and xterm.js consoles need a websocket location; the role sets no websocket proxy flavour yet.
- **Two sessions:** the OAuth2 proxy cookie and the Proxmox VE ticket live independently. The universal logout ends both in the browser, but no back-channel logout reaches Proxmox VE: a copied ticket stays valid for up to two hours after its last renewal.
- **Guest upgrades:** a raised ISO pin installs new guests only; an existing guest keeps its release until it is upgraded in place.

## Broker token

The broker gets one privilege-separated API token per Infinito.Nexus instance, bound to one resource pool. Its role holds exactly these privileges, on that pool and on the agent storage only:

- `VM.Allocate`, `VM.Clone`, `VM.Audit`, `VM.PowerMgmt`
- `VM.Config.CPU`, `VM.Config.Memory`
- `VM.GuestAgent.Audit`, `VM.GuestAgent.FileRead`, `VM.GuestAgent.FileWrite`, `VM.GuestAgent.Unrestricted`
- `Datastore.AllocateSpace`, `Datastore.Audit` on the agent storage
- `Pool.Audit` on the agent pool

`VM.Config.Network`, `VM.Config.Disk`, `VM.Config.HWType`, `Sys.*` and every privilege outside the pool are left out, so the token cannot move a VM to another bridge, add a host or foreign-storage disk, or touch a VM outside the pool.

## Login

1. The OAuth2 proxy sends the visitor to Keycloak and admits only members of the administrator group.
2. Proxmox VE shows its login window with the OpenID realm preselected; `Login (OpenID redirect)` completes silently through the Keycloak session and creates the account `<username>@<realm>` on first login.
3. The user menu's `Logout` triggers the universal logout, which ends the Keycloak session and deletes both the OAuth2 proxy cookie and `PVEAuthCookie`.

A password login of a `@pam` or `@pve` account fails. The deploy sets the second factor `PROXMOX_LOCAL_REALM_TFA` (`type=oath`) as required on both realms (`PROXMOX_LOCAL_REALMS`), and no account of them holds one, so Proxmox VE refuses the login after the password. The root password is locked as well: by the first-boot hook under `vm` and in the image under `container`. API tokens, such as `ws-<id>@pve!provision`, authenticate without a realm login and keep working. The Playwright test `proxmox login: a @pam or @pve password login through the public domain fails` reads the realm setting and proves the refusal with a `@pve` account whose password is right.

Break-glass access goes through the container shell, never through the public domain: `pveum` as root inside the container under `container`, and `pve-guest pveum` inside the launcher under `vm`.

## Persona contract opt-outs

The `administrator` persona runs the role-local flow [`files/playwright/proxmox-flow.js`](./files/playwright/proxmox-flow.js): the OAuth2 proxy login, the OpenID realm login, the `Administrator` grant of its group on `/`, and the logout. [`meta/services.yml`](./meta/services.yml) admits only the `web-app-proxmox` administrator RBAC group to the OAuth2 proxy (`sso.oauth2.allowed_groups`) and `biber` carries no roles, so [`templates/playwright.env.j2`](./templates/playwright.env.j2) renders `PERSONA_BIBER_BLOCKED=true`. The `guest` persona and the baseline assertion run unconditionally.

## Further Resources

- [Proxmox VE documentation](https://pve.proxmox.com/pve-docs/)
- [Proxmox VE automated installation](https://pve.proxmox.com/wiki/Automated_Installation)
- [Proxmox VE nested virtualization](https://pve.proxmox.com/wiki/Nested_Virtualization)
- [Proxmox VE package repositories](https://pve.proxmox.com/wiki/Package_Repositories)
- [Proxmox VE user management](https://pve.proxmox.com/wiki/User_Management)
