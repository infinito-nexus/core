# Systemd Services ⚙️

These playbooks stop and start every `*.infinito.nexus` timer and service on the hosts of an inventory.

## Shut Down 🛑

Run from the repository root:

```bash
ansible-playbook -i <inventory> playbooks/services/down.yml
```

The playbook stops and disables every `*.infinito.nexus` timer, then stops every `*.infinito.nexus` service.
Disabled timers stay off after a reboot.
A service that is running at that moment, such as a backup, is aborted.

Shut down the compose stacks afterwards with the [Compose](../compose/README.md) playbooks.

## Start 🚀

You SHOULD start the compose stacks first with the [Compose](../compose/README.md) playbooks.

Run from the repository root:

```bash
ansible-playbook -i <inventory> playbooks/services/up.yml
```

The playbook enables and starts every `*.infinito.nexus` timer.
The services run on their timer schedule and are not started directly.
