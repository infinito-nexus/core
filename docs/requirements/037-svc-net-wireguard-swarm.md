# 037 - svc-net-wireguard: WireGuard Transport for Swarm Deployments

## User Story

As an operator of a swarm deployment, I want every swarm deploy to carry its control, storage and management traffic through WireGuard tunnels provisioned from the inventory, so that no swarm or storage port is reachable outside the mesh and a broken tunnel stops the deploy instead of silently falling back to the underlay.

## Context

The swarm topology this requirement runs on already exists and is green. `default.env` is its SPOT and names exactly five hosts on the `swarm-lab` subnet `192.168.244.0/24`:

| Entity | `default.env` name | Underlay address |
| --- | --- | --- |
| Manager | `INFINITO_SWARM_MGR_NAME` = `swarm-mgr-01` | `192.168.244.10` |
| Node 1 | `INFINITO_SWARM_WRK1_NAME` = `swarm-wrk-01` | `192.168.244.11` |
| Node 2 | `INFINITO_SWARM_WRK2_NAME` = `swarm-wrk-02` | `192.168.244.12` |
| NFS Server | `INFINITO_SWARM_NFS_NAME` = `nfs-server` | `192.168.244.13` |
| Backup Server | `INFINITO_SWARM_BACKUP_NAME` = `swarm-bkp-01` | `192.168.244.14` |

Nothing here adds hosts. It puts a tunnel under the five that are already deployed.

### Two planes, one hub

Two hub-and-spoke networks are stacked over that underlay, and the Manager is the only host in both:

| Network | Hub | Spokes | Carries |
| --- | --- | --- | --- |
| SWARM VPN | `swarm-mgr-01` | `swarm-wrk-01`, `swarm-wrk-02` | swarm control (`2377`), gossip (`7946`), overlay data (`4789`) |
| DATA VPN | `swarm-mgr-01` | `nfs-server`, `swarm-bkp-01` | NFS exports, backup transfer |

Spokes peer only with the hub, so every path that does not start or end at the Manager is routed by it. Three consequences follow and are accepted rather than worked around:

- Worker-to-worker overlay traffic crosses the Manager twice. Plain swarm keeps running containers talking when a manager is lost; this topology does not, because the hub is also the data path.
- Workers are not members of the DATA VPN, and they require NFS. All worker storage traffic is therefore routed through the Manager between the two planes, which makes the hub the throughput ceiling for storage as well as for east-west traffic.
- The hub needs forwarding enabled and `AllowedIPs` wide enough to cover the far plane, so a spoke's routes are only as correct as the hub's.

### Why a new CLI tool

Every credential generator in the repository is single-host scoped. `cli/administration/inventory/provision/credentials_generator.py` shells out to `cli.administration.inventory.credentials` once per `(app_id, host_vars_file)` pair, and that subprocess sees one host's inventory with no knowledge of any other. WireGuard is the first credential the platform needs that is **correlated across hosts**: the Manager's configuration has to contain the workers' public keys, and each worker has to contain the Manager's. No existing generator can express "this value depends on a secret minted for a different host".

The tool this requirement introduces supplies that missing capability, and it is specified as cross-host credential generation rather than as a WireGuard utility, so that later consumers — cluster join tokens, shared HMAC secrets, mesh certificates, anything paired — reuse it instead of repeating it.

That framing also settles rotation. The platform regenerates generated-algorithm credentials on every deploy by design. For a mesh that is ordinarily fatal, because rotating one host's key invalidates its entry in every peer's configuration. Because the tool writes all five inventories in a single pass **before** Ansible runs, it is the only writer that ever sees the whole mesh, and the rotation is atomic by construction.

### Transport, and why it is two-phase

Ansible reaches the nodes over the tunnel, which cannot be true for the whole run:

- On a first deploy no tunnel exists yet, so the connection that creates it must use the underlay.
- Keys rotate every deploy, so applying a new configuration drops the connection carrying it. On the hub that severs the path to every spoke at once.

The deploy is therefore split at an explicit seam, and the seam falls between two passes that already exist. Pass one provisions WireGuard over whatever transport reaches the hosts today, because it is the pass that creates the tunnel. The gate runs. The inventory is then rewritten — `ansible_host` to the mesh address, the connection to SSH — and pass two deploys every role over the tunnel. No extra round and no extra CI time: the update pass was already there, and a full deploy of every role over the mesh proves more than a narrow bootstrap round would.

The rewrite is a step between the passes rather than a fact set during a play, because a play cannot change the transport it is already running over.

The Ansible controller is a mesh member. It is not a swarm node and joins no cluster, but it holds an address and routes the pool through the hub, so the second pass reaches every host over the tunnel rather than through a gateway hop. It is named explicitly rather than resolved from an inventory group: it has no role group of its own, and inventing one would put a non-role name into `group_names`, where every service and placement lookup would have to special-case it.

That makes the mesh load-bearing rather than merely present. If it is broken the deploy cannot reach a single host, so no role can quietly fall back to the underlay it was supposed to stop using.

### The gate is binary

`Layer is Working?` has two outcomes and no third: either the deploy proceeds, or none of it does. The check sits between WireGuard coming up and swarm initialising, and a failure fails the deploy loudly.

Whether a given swarm deploy carries the mesh at all is a separate question, decided per run by the `vpn` axis. The two do not soften each other: when the axis is on, the mesh is mandatory and a regression stops the job; when it is off, the role is absent from the inventory entirely rather than deployed disabled, so that arm proves swarm still works with no mesh logic anywhere in the path. Swarm and the mesh are independent — a production swarm can run inside one isolated physical environment, and the mesh exists to join clusters that are physically separated — so a swarm deploy must not depend on one being present.

### Known trap: MTU

The overlay stacks VXLAN inside WireGuard, and a path that silently exceeds the usable size fails as intermittent large-payload loss rather than as a clean error — which reads like flaky CI.

The size is measured, not declared. `automtu` already derives the docker daemon's MTU, and a second hardcoded pair could only contradict it; the role runs the same probe against the hub's underlay endpoint and subtracts the WireGuard and VXLAN headers from what comes back. The endpoint is used rather than the mesh address because the interface those MTUs configure is not up yet when the measurement is taken.

### Scope

Swarm mode only, and there only when the run's `vpn` axis asks for it. The role is inert in compose mode, which is a single host with nothing to tunnel between. SOC and Wazuh visibility are out of scope. Deployment testing of a role running over the mesh follows implementation and is not part of this requirement's criteria.

## Acceptance Criteria

- [x] A CLI tool generates credentials whose values are correlated across hosts, and its interface names no role, so a later consumer reuses it without modification.
- [x] The tool takes the host set as input and writes every affected inventory in one invocation, so no deploy can observe a mesh in which one host has been rotated and another has not.
- [x] Each host's inventory carries one WireGuard private key identifying it on every mesh it belongs to, and the public key of every peer it is configured to reach; no host's inventory contains another host's private key.
- [x] Every generated private key is vault-encrypted in the inventory, matching the treatment of every other platform credential.
- [x] Re-running the tool without a rotation request leaves an existing mesh byte-identical, so a deploy that changes nothing changes nothing.
- [ ] The SWARM VPN is established between `swarm-mgr-01`, both workers and the controller, and the DATA VPN between `swarm-mgr-01`, `nfs-server` and `swarm-bkp-01`, with membership derived from the `default.env` topology rather than restated.
- [ ] A worker reaches the NFS export over the mesh, routed by the Manager, and the same mount fails when the Manager's tunnel is down.
- [x] The WireGuard subnets collide with neither `192.168.244.0/24`, nor the Docker address pools, nor any per-role subnet, and a collision is caught before deploy rather than at runtime.
- [ ] Swarm advertises and listens on its mesh address, so `docker info` on every node reports the mesh address and not an underlay or public one.
- [ ] No swarm or NFS port is reachable from outside the mesh on any of the five hosts.
- [ ] The first pass runs over the pre-existing transport and the second over the mesh, against hosts that had no tunnel when the deploy started, without manual intervention.
- [ ] The Ansible controller holds a mesh address and reaches every member over the tunnel, while joining no swarm cluster.
- [ ] Reconfiguring a live interface does not drop the connection the play is running over, so a key rotation converges on a host Ansible is reaching through the mesh.
- [x] Rotating every key on a redeploy does not sever the run, and the mesh converges without an operator touching a node.
- [ ] The gate runs between WireGuard coming up and swarm initialising, and a deliberately broken tunnel fails the deploy at that gate with a message naming the unreachable peer, before any swarm or role task runs.
- [ ] A swarm deploy with the mesh on carries every path over it, and a regression in the layer fails the deploy rather than falling back.
- [ ] A swarm deploy with the mesh off omits the role from the inventory entirely and still reaches a green deploy, so nothing in the swarm path depends on the mesh being present.
- [ ] The mesh state rotates per run, is pinnable from a selection token, and is readable off a job title.
- [ ] The role is inert in compose mode, and a compose deploy neither installs WireGuard nor runs the gate.
- [ ] The MTU is measured for the VXLAN-inside-WireGuard path rather than declared, and a full-size payload crosses the mesh without fragmentation or loss.
- [x] Unit tests cover the tool as a pure function of its inputs: mesh completeness, peer-key pairing, private-key containment and rotation idempotence, none of them requiring a deploy.
- [x] Lint, external and integration suites pass for the role and the tool.
- [ ] The role provisions its own WireGuard tooling; no test image pre-bakes it.

## See Also

- [023 - Docker Swarm Deployment with NFS-backed Shared Volumes](023-docker-swarm-nfs.md)
