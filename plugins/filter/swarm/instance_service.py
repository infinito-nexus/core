"""Name the stack service of one HA database instance or of its sidecar."""

from __future__ import annotations

from utils.roles.db.instances import instance_service


def swarm_instance_service(instance, application_id, service_key=None) -> str:
    """Return the stack service key of *instance* or of its per-host sidecar.

    Args:
        instance: an entry of ``lookup('db_instances').instances``.
        application_id: engine role, e.g. ``svc-db-redis``.
        service_key: a sidecar service key such as ``sentinel``; omitted for
            the instance itself.
    """
    return instance_service(application_id, instance, service_key)


class FilterModule:
    def filters(self):
        return {"swarm_instance_service": swarm_instance_service}
