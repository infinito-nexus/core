# Shared Target 🎯

Build context and resolver configuration of the `target` and `target-resolver` services in [compose.yml](../../compose.yml): a bare foreign server that deploy tests reach over SSH, the way an operator reaches a managed server. A compose round reaches it from the `infinito` container, a swarm round from the swarm nodes.

## Services 🧩

| Service | What runs there |
| --- | --- |
| `target` | systemd and an ssh server on the distribution base image, nothing else; built from [Dockerfile](Dockerfile) and [init.sh](init.sh) with `INFINITO_PARENT_IMAGE` as base |
| `target-resolver` | CoreDNS at its own address `INFINITO_TARGET_RESOLVER_IP`, the resolver a provider hands a managed server; answers `INFINITO_DOMAIN` and every name under it with `INFINITO_TARGET_IP` and forwards the rest to the stack's CoreDNS at `INFINITO_DNS_IP`, which starts with it. It holds no socket on the target, and `init.sh` turns off the stub listener of `systemd-resolved` the base image may run, as the stack's [Dockerfile](../../Dockerfile) does, so port 53 of the target stays free on every address for a replayed DNS server such as [svc-dns-knot](../../roles/svc-dns-knot/README.md) |

The target carries no container engine and no SSH host key of its own: a deploy under test installs `docker-ce`, and `target-host-keys.service` generates host keys when a container boots. Its `/var/lib/docker` is the named volume `INFINITO_RUNNER_PREFIX-target-docker`, so the engine a deploy installs writes to a real filesystem. The volume is named, not anonymous, because `sys-ctl-hlth-volumes` fails on every anonymous volume of the outer daemon, which is the operator's own host on a workstation that also runs a deployed stack. The checkout is mounted at `INFINITO_SRC_DIR`, where a host install replays from it.

## Addressing 🧭

| What | Value |
| --- | --- |
| Address | `INFINITO_TARGET_IP`, host `.20` of `INFINITO_SUBNET`, derived by [target_ip.py](../../utils/env/handlers/infinito/target_ip.py) so every worktree and runner instance gets its own |
| Resolver address | `INFINITO_TARGET_RESOLVER_IP`, host `.21` of `INFINITO_SUBNET`, derived by the same handler |
| Lab address | in a swarm round also host `.20` of the lab network's subnet (`192.168.244.20` in CI, `10.160.<slot>.20` in a worktree), next to the nodes at `.10` to `.14` |
| Hostname | `target`; Docker's DNS answers it on the stack network and, through the network alias the reset sets, on the lab network; the stack's CoreDNS answers it for containers inside the `infinito` daemon, and each lab node's dnsmasq forwards it to Docker's DNS |
| Container | `${INFINITO_RUNNER_PREFIX}-target` and `${INFINITO_RUNNER_PREFIX}-target-resolver` |
| Root key | `INFINITO_TARGET_KEY` on every holder: the `infinito` container in a compose round, each swarm node in a swarm round. `.pub`, `.known_hosts` and `.address` sit beside it; `.address` is where that holder reaches the target |

## Reset 🔄

[target.py](../../cli/administration/deploy/development/target.py) is the one reset. It runs on the host, because only the host daemon can recreate the target:

```bash
make compose-target-reset
```

`make compose-up` runs it after the stack is up, and `python -m cli.administration.deploy.development deploy` runs it before every pass of every round, so the update pass of a full cycle starts on a bare target too. The swarm matrix runs the same reset before every pass of every swarm round ([deploy.py](../../utils/tests/swarm/deploy.py) `deploy_round`), with the lab network and the swarm nodes:

```bash
python -m cli.administration.deploy.development target-reset \
  --lab "${SWARM_LAB_NETWORK}" --node "${MGR}" --node "${WRK1}" --node "${WRK2}"
```

`coredns` starts with `target-resolver`, so the reset needs no running `infinito` container. A reset:

1. renders the stack's [Corefile.tmpl](../coredns/Corefile.tmpl) and this [Corefile.tmpl](Corefile.tmpl) into their `Corefile`;
2. removes `target`, `target-resolver` and the `/var/lib/docker` volume, then builds and starts both again;
3. in a swarm round, connects the new target to the lab network at its lab address, under the alias `target`;
4. waits until systemd reports `running` or `degraded`;
5. points the target's `/etc/resolv.conf` at `INFINITO_TARGET_RESOLVER_IP` and waits until a name under `INFINITO_DOMAIN` resolves to the target's own address;
6. generates a new ed25519 pair at `INFINITO_TARGET_KEY` on every holder and authorizes all public halves for `root` on the target;
7. writes the target's new host keys to `INFINITO_TARGET_KEY.known_hosts` on every holder, under the address that holder uses and under `target`, and that address to `INFINITO_TARGET_KEY.address`;
8. in a swarm round, waits until `target` resolves to the lab address on every node;
9. logs in from every holder with `StrictHostKeyChecking=yes` against its file.

The swarm teardown disconnects the target from the lab network before it removes that network, and `make swarm-clean` does the same; the target itself stays with the stack.

## Using it 🔑

- Connect as `root@$(cat "$INFINITO_TARGET_KEY.address")` with `-i "$INFINITO_TARGET_KEY" -o StrictHostKeyChecking=yes -o UserKnownHostsFile="$INFINITO_TARGET_KEY.known_hosts"`. Every reset changes the host keys, so a `known_hosts` that outlives a reset fails with a changed host key; never pin them anywhere else.
- Claim the target before the first change with `mkdir /var/lib/infinito-target-claim` over SSH. The claim fails once anything used the target since its last reset, so two uses of one target run one after another and never on top of each other.
- The target is not on the cache network, so it pulls packages and images from their upstream registries like a foreign server does.

## Files 📄

| File | Role |
| --- | --- |
| `Dockerfile` | builds the target from `INFINITO_PARENT_IMAGE` and boots `/sbin/init` |
| `init.sh` | installs systemd and an ssh server, removes the host keys, installs `target-host-keys.service`, turns off the `systemd-resolved` stub listener on port 53, masks the units that escape a container |
| `.dockerignore` | keeps the build context to `Dockerfile` and `init.sh` |
| `Corefile.tmpl` | the resolver's configuration; `${INFINITO_DOMAIN}`, `${INFINITO_TARGET_IP}`, `${INFINITO_TARGET_RESOLVER_IP}` and `${INFINITO_DNS_IP}` come from `.env` |
| `Corefile` | rendered output, bind-mounted into `target-resolver`; ignored by git |
