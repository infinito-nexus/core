"""Central "engine" dependencies (cache / queue / search / vector / DNS resolver).

A role may consume an engine either *embedded* (a sidecar inside its own stack) or
*central* (a single pinned ``svc-db-*`` / ``svc-dns-*`` stack shared by many roles),
selected per consumer with the ``shared`` flag exactly like the RDBMS
(postgres / mariadb) pattern in :mod:`utils.roles.applications.services.database`.

See ``docs/architecture/central-engines.md`` for the rationale (engine on-disk state
cannot live on NFS, so centralising it keeps the application roles unpinned and
NFS-shareable in swarm).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

# Engine service-key -> descriptor.
#   svc:       central role id that owns the engine when ``shared: true``.
#   port:      default container port.
#   isolation: how a consumer gets its own logical slice on the central instance.
#              acl  -> dedicated user + key-prefix (redis)
#              vhost-> dedicated virtual host + user (rabbitmq)
#              index-> dedicated index/alias namespace (elasticsearch)
#              apikey -> scoped api key (typesense)
#              collection -> per-consumer collection prefix (qdrant)
#              prefix -> key-prefix only, no enforcement (memcached)
#              none -> shared, no per-consumer split (unbound resolver)
ENGINES: dict[str, dict[str, Any]] = {
    "redis": {"svc": "svc-db-redis", "port": 6379, "isolation": "acl"},
    "memcached": {"svc": "svc-db-memcached", "port": 11211, "isolation": "prefix"},
    "rabbitmq": {"svc": "svc-db-rabbitmq", "port": 5672, "isolation": "vhost"},
    "elasticsearch": {
        "svc": "svc-db-elasticsearch",
        "port": 9200,
        "isolation": "index",
    },
    "typesense": {"svc": "svc-db-typesense", "port": 8108, "isolation": "apikey"},
    "qdrant": {"svc": "svc-db-qdrant", "port": 6333, "isolation": "collection"},
    "unbound": {"svc": "svc-dns-unbound", "port": 53, "isolation": "none"},
}

ENGINE_KEYS = tuple(ENGINES)


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def get_services(
    applications: Mapping[str, Any], application_id: str
) -> dict[str, Any]:
    return _as_mapping(_as_mapping(applications.get(application_id)).get("services"))


def engine_service(
    applications: Mapping[str, Any], application_id: str, engine: str
) -> dict[str, Any]:
    """The consumer's ``services.<engine>`` block (or empty)."""
    return _as_mapping(get_services(applications, application_id).get(engine))


def is_engine_enabled(
    applications: Mapping[str, Any], application_id: str, engine: str
) -> bool:
    return bool(engine_service(applications, application_id, engine).get("enabled"))


def is_engine_shared(
    applications: Mapping[str, Any], application_id: str, engine: str
) -> bool:
    """Consumer wants the central instance (``enabled`` and ``shared``)."""
    svc = engine_service(applications, application_id, engine)
    return bool(svc.get("enabled")) and bool(svc.get("shared"))


def is_engine_embedded(
    applications: Mapping[str, Any], application_id: str, engine: str
) -> bool:
    """Consumer wants an embedded sidecar (``enabled`` and not ``shared``)."""
    svc = engine_service(applications, application_id, engine)
    return bool(svc.get("enabled")) and not bool(svc.get("shared"))


def central_consumers(applications: Mapping[str, Any], engine: str) -> list[str]:
    """Roles consuming ``engine`` as ``shared: true`` -- drives on-demand enable of
    the central engine stack (deploy it only when at least one role needs it)."""
    return sorted(
        application_id
        for application_id in applications
        if is_engine_shared(applications, application_id, engine)
    )


def central_engine_needed(applications: Mapping[str, Any], engine: str) -> bool:
    return bool(central_consumers(applications, engine))
