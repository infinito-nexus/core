# WireGuard: three meshes around one hub

An inventory with **three** WireGuard meshes, to show that the number of meshes
and the hosts in them belong to the deployment rather than to this repository.
Nothing here is special-cased: the same CLI, role and planner serve it, and
every role ships its mesh fields empty.

## The topology

| mesh | subnet | port | hub | spokes |
|---|---|---|---|---|
| `alpha` | `10.100.10.0/24` | 51830 | `mesh-hub-01` | `svc-swarm-node` |
| `beta` | `10.100.11.0/24` | 51831 | `mesh-hub-01` | `svc-storage-nfs-server` |
| `gamma` | `10.100.12.0/24` | 51832 | `mesh-hub-01` | the five `svc-bkp-*` roles |

The host carrying `svc-swarm-manager` is the hub of every mesh, which is what
lets a spoke of one reach a spoke of another: every spoke routes the whole
`NETWORK_MESH_POOL` through its hub. Two meshes with no host in common cannot
reach each other, by design.

Declaration order matters once: each host's first declared mesh is its
**primary**. That is the address the other planes reach it on, the mesh a
deploy controller joins, and the one interface a spoke of several meshes
routes the pool through. Its other interfaces route only their own subnet,
because two interfaces claiming one range is a route `wg-quick` refuses.

## Where the values go

[wireguard.yml](wireguard.yml) holds the layout as ordinary `applications`
values:

- `svc-net-wireguard.networks.meshes` declares the meshes. It belongs in the
  hub's `host_vars`, which is where the mesh CLI reads it.
- `<role>.networks.meshes` lists the meshes a role puts its hosts into. It
  belongs in the `host_vars` of the hosts carrying that role, and may differ
  per host, so two hosts of one role can sit in different meshes.

`host_vars` is the place because a host's `applications` there replaces any
set in `group_vars`, and provisioning always writes one.

## Running it

The mesh is written by one cross-host pass before the play, never by the role:

```bash
python3 -m cli.administration.inventory.mesh \
  --inventory   inventories/examples/wireguard-three-meshes/inventory.yml \
  --host-vars-dir <your host_vars dir> \
  --vault-password-file <your password file>
```

It writes each host's own addresses, keys and peers into
`svc-net-wireguard.networks.interfaces` of that host's `host_vars`.

## Testing it end to end

The swarm lab has the same five hosts in the same groups as `inventory.yml`,
under its own names. Point a meshed swarm round at this layout and it deploys a
role over all three meshes:

```bash
make swarm-zombie app=<role> vpn=enforced \
  meshes=inventories/examples/wireguard-three-meshes/wireguard.yml
```

In CI, dispatch the manual workflow with the same three choices:

```bash
gh workflow run entry-manual-steer.yml --ref <branch> \
  -f whitelist=<role> -f mode=swarm -f vpn=enforced \
  -f meshes=inventories/examples/wireguard-three-meshes/wireguard.yml
```

The lab bakes the whole block into every host, which is enough because a host
only counts the roles it carries. It is also slightly stricter than this
inventory: its NFS server keeps its own backup leg, so `svc-bkp-nfs-2-local`
makes it a spoke of `gamma` as well as `beta`, and a run proves a spoke of two
meshes.
