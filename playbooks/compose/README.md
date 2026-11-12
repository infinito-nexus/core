# Compose Stacks 🐳

These playbooks stop and start every compose stack below `/opt/compose/` on the hosts of an inventory.
They cover compose deployments only and do not touch swarm stacks.

## Shut Down 🛑

You SHOULD stop the timers and services first with the [Services](../services/README.md) playbooks.

Run from the repository root:

```bash
ansible-playbook -i <inventory> playbooks/compose/down.yml
```

The playbook runs `compose down` in every directory directly below `/opt/compose/` that contains a `compose.yml`.
A directory that contains a `docker-compose.yml` instead gets `docker compose down --remove-orphans`.
Containers and project networks are removed.
Volumes and shared networks declared as `external: true` stay in place.

To shut down the stacks of another base directory, such as the deprecated `/opt/docker/` layout, pass `compose_dir`:

```bash
ansible-playbook -i <inventory> playbooks/compose/down.yml -e compose_dir=/opt/docker/
```

## Start 🚀

Run from the repository root:

```bash
ansible-playbook -i <inventory> playbooks/compose/up.yml
```

The playbook runs `compose up -d` in the same directories, in any order.
Start the timers afterwards with the [Services](../services/README.md) playbooks.
