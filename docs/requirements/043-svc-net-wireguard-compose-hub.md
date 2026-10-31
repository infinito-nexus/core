# 043 - WireGuard Hub for Compose Deployments

## User Story

As an operator of compose hosts, laptops and hosts behind NAT, I want `svc-net-wireguard` to build a hub-and-spoke mesh around a host I name, without a swarm manager, so that roaming and NATed members reach every other member through the hub and a deploy never waits on a member that is offline.

## Acceptance Criteria

- [ ] An explicit inventory value names the hub of a compose deployment, and `cli.administration.inventory.mesh` plans hub-and-spoke meshes around it without any host in `svc-swarm-manager`.
- [ ] The hub forwards between the spokes of its meshes, so a spoke reaches every other spoke through the hub.
- [ ] A spoke marked as roaming gets no endpoint in the hub's peer list and dials the hub with `PersistentKeepalive`.
- [ ] The hub's handshake gate skips roaming spokes, and a roaming spoke's own deploy gates only on the hub.
- [ ] A mesh keeps an operator-chosen subnet and listen port, such as `10.0.0.0/24` on UDP 51871.
- [ ] Deployments that name no hub and have no `svc-swarm-manager` keep planning full meshes exactly as before.
- [ ] Swarm deployments keep the `svc-swarm-manager` host as their hub exactly as before.
- [ ] The planner and the role changes have unit tests, and `make test` passes.
