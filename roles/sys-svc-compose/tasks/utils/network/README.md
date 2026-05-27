# Network utils 🕸️

Reusable task files for creating Docker networks in a uniform way.
Both helpers derive the docker-side network name from `role_id | get_entity_name` and the subnet from `meta/server.yml.networks.local.subnet`, so the name and the subnet pinning live in exactly one place.

Ad-hoc `community.docker.docker_network` calls or `docker network create` / `container network create` shell-outs in role tasks are forbidden by [test_network_create_via_util.py](../../../../../tests/lint/ansible/modules/test_network_create_via_util.py).

## When to use which 🧭

### `create.yml`: network only, no compose-up

Use when the role still has work to do between the network creation and the compose-up.
Examples: copy `entrypoint.sh` / `healthcheck.sh` into the instance directory before the container starts, render additional configs, pre-attach other resources.
Also the right choice when pre-creating several foreign networks in a loop (e.g. prometheus's `native_metrics_apps` pre-create), where firing the compose handler per iteration would be wrong.

Required var:

- `network_role_id`: the role whose network to create. Name and subnet are derived from it.

```yaml
- include_tasks: "{{ [playbook_dir, 'roles/sys-svc-compose/tasks/utils/network/create.yml'] | path_join }}"
  vars:
    network_role_id: "{{ application_id }}"
```

### `routine.yml`: wrapper with immediate compose-up

Use when the role is a self-contained single-container service whose only pre-condition for compose-up is its own network (e.g. `svc-db-mariadb`, `svc-db-postgres`, `svc-ai-ollama`).
The wrapper loads the docker-python deps, calls `create.yml` for the role's own network (via `application_id`), and then re-includes `sys-svc-compose` with `compose_handlers_flush: true` so the compose-up fires right after.

```yaml
- include_tasks: "{{ [playbook_dir, 'roles/sys-svc-compose/tasks/utils/network/routine.yml'] | path_join }}"
  vars:
    compose_handlers_flush: true
```

## Decision rule 📌

Pick `routine.yml` when "create network → compose-up immediately" is the entire pre-condition chain.
Pick `create.yml` in every other case.
