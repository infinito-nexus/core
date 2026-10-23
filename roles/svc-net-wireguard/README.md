# WireGuard

## Description

[WireGuard](https://www.wireguard.com/) is an in-kernel VPN protocol. Peers
authenticate each other with Curve25519 keypairs and exchange encrypted UDP
datagrams, so a tunnel needs no session state, no certificate authority and no
daemon of its own.

## Overview

This role puts WireGuard under a swarm deployment so that swarm control,
overlay and storage traffic never crosses an untunnelled network. It configures
the hub-and-spoke meshes the deployment declares, any number of them, with the
swarm manager as the hub of each. The manager forwards between them, which is
how a worker reaches an NFS export it is not a member of.

Without a swarm manager, as in a Compose deployment spread over several hosts,
the inventory may name a hub in `networks.hub`. That host then plays the
manager's part: it is the hub of every declared mesh and forwards between its
spokes, so laptops and hosts behind NAT reach each other through it. A spoke
marked `networks.roaming: true` has no endpoint in the hub's peer list; it
dials the hub and keeps the path open from its side.

With neither a swarm manager nor a named hub, every declared mesh is a full
mesh. Each member knows the key of every other member and dials it directly,
and nothing forwards between meshes: a host reaches exactly the members of the
meshes it joined.

The meshes are inventory values, and every role ships them empty.
`networks.meshes` of this role declares them in the hub's `host_vars`, or in
the `host_vars` of every member when there is no hub, and `networks.meshes` of
every other role lists the meshes its hosts join. A host that carries no other
role on the mesh joins by listing the mesh name in this role's own
`networks.meshes`; a mapping there declares a mesh, a name joins one. The
development lab declares two, `swarm` and `data`, in
[wireguard.yml](../../inventories/development/wireguard.yml);
[wireguard-three-meshes](../../inventories/examples/wireguard-three-meshes/README.md)
declares three. Consumers read a host's mesh address through
`lookup('mesh_address', <host>)` instead of naming a mesh.

The role plans nothing. Every key, address and peer list is written into the
inventory beforehand by `cli.administration.inventory.mesh`, the one pass that
sees every host at once; this role renders what its own host was handed and
then proves the result. It acts on every host in the `svc-net-wireguard`
group; outside swarm mode a host the mesh CLI gave no mesh is skipped.

## Features

- Any number of hub-and-spoke meshes around one hub, so the planes stay
  separate while remaining mutually reachable.
- A hub named in the inventory for Compose deployments, with roaming spokes
  that dial it with `PersistentKeepalive` and are never waited for.
- Full meshes when the inventory has no hub, each member peered with every
  other and no route between meshes.
- A host may be a spoke of several meshes: it routes the pool through its
  first declared one and only the mesh subnet through the others, so no two
  interfaces claim one route.
- Per-host interfaces rendered from inventory state, with each private key
  vault-encrypted in exactly one host's `host_vars`.
- Forwarding enabled only on the hub, which is the only member with peers in
  every plane.
- A hard gate that fails the deploy before swarm initialises when an awaited
  peer never handshakes or the path will not carry a full-size payload. A spoke
  awaits its hub, a full-mesh member every peer, a named hub every spoke that
  does not roam, and the swarm manager none.

## Administration

The mesh must exist in the inventory before the play runs. Write it once over
every inventory of the deploy, including any sibling file that holds hosts the
cluster inventory does not:

```bash
python3 -m cli.administration.inventory.mesh \
  --inventory /tmp/inv/devices.yml \
  --inventory /tmp/inv/backup.yml \
  --host-vars-dir /tmp/inv/host_vars \
  --vault-password-file /tmp/inv/.password
```

It reads the declarations and memberships from the `host_vars` it writes to,
and records each host's addresses, keys and peers in that host's
`svc-net-wireguard.networks.interfaces`.

Re-running is a no-op. To replace every keypair, add `--rotate`; that rewrites
the whole mesh in one pass, because rotating one member alone partitions it.

### Compose hosts

For Compose hosts the inventory holds no `svc-swarm-manager`, so the writer
plans full meshes. Put the same `svc-net-wireguard.networks.meshes`
declaration into the `host_vars` of every member, list the meshes a host joins
under `networks.meshes` of a role it carries, add the hosts to the
`svc-net-wireguard` group, write the mesh as above and deploy. Each member
listens on the mesh port, so that UDP port must be open between the members.
The role brings the interfaces up and gates on a handshake with every peer;
an application uses the tunnel only where it is pointed at a peer's mesh
address, which `lookup('mesh_address', <host>)` returns.

### Compose hub

When laptops or hosts behind NAT take part, name one reachable host as the hub
instead. Its `host_vars` declare the meshes and name it:

```yaml
applications:
  svc-net-wireguard:
    networks:
      hub: galaxyserver
      meshes:
        - name: wg0
          subnet: 10.0.0.0/24
          listen_port: 51871
```

Every spoke joins through a role it carries or, lacking one, through this
role's own list, and a laptop is marked roaming:

```yaml
applications:
  svc-net-wireguard:
    networks:
      meshes: [wg0]
      roaming: true
```

Write the mesh with the hub's public address as its endpoint:

```bash
python3 -m cli.administration.inventory.mesh \
  --inventory servers.yml \
  --inventory pcs.yml \
  --host-vars-dir host_vars \
  --vault-password-file .password \
  --endpoint galaxyserver=vpn.example.org
```

- Only the hub listens, so only its UDP port must be reachable. Every spoke
  dials it with `PersistentKeepalive = 25` and routes the mesh range through
  it; the hub enables `net.ipv4.ip_forward` and forwards between them. On a
  Docker host whose `FORWARD` policy is `DROP`, accept traffic between the mesh
  interfaces in that chain.
- The hub's deploy waits for every spoke that does not roam, a roaming
  spoke's deploy only for the hub. Deploy the hub first.
- A subnet outside `NETWORK_MESH_POOL` is refused; set the pool in the
  inventory's `group_vars` to a range holding it.
- A spoke keeps an address it already holds. To carry over an address from an
  earlier setup, list it before the first run as
  `networks.interfaces: [{name: wg0, host: <host>, address: <address>}]`.
- A host deployed with its own vault password takes
  `--host-vault-password-file <host>=<file>`, so its private key opens there.
- A mesh is IPv4 only.

Inspect a live interface on any member:

```bash
wg show <mesh-name>
```

A peer with no recent handshake is either unreachable on the underlay or
carrying a key its peer does not know. The second case means the inventory and
the running interface disagree: re-run the mesh writer and redeploy rather than
editing `/etc/wireguard` by hand, which the next deploy overwrites.
