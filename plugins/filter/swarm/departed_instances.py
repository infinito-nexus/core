"""Name the per-host engine services whose host left the engine group."""

from __future__ import annotations

from ansible.errors import AnsibleFilterError

from utils.roles.db.instances import DbInstancesError, departed_instance_services


def swarm_departed_instances(
    live_services, application_id: str, stack: str, declared_services
) -> list[str]:
    """Return the live services to remove explicitly after a stack deploy.

    Args:
        live_services: ``docker stack services`` names, ``<stack>_<service>``.
        application_id: engine role, e.g. ``svc-db-redis``.
        stack: swarm stack name of the engine.
        declared_services: service keys of the rendered compose file.
    """
    try:
        return departed_instance_services(
            application_id, stack, live_services or [], declared_services or []
        )
    except DbInstancesError as exc:
        raise AnsibleFilterError(str(exc)) from exc


class FilterModule:
    def filters(self):
        return {"swarm_departed_instances": swarm_departed_instances}
