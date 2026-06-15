from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import dump_yaml_str

try:
    from plugins.filter.docker_service_enabled import (
        FilterModule as _DockerServiceEnabledFilter,
    )
    from plugins.filter.get_entity_name import get_entity_name
    from utils.roles.applications.config import get
    from utils.roles.applications.services.database import (
        get_database_service_config,
        resolve_database_service_key,
    )
    from utils.roles.applications.services.sso import get_sso_config
except ModuleNotFoundError:
    from docker_service_enabled import FilterModule as _DockerServiceEnabledFilter
    from get_entity_name import get_entity_name

    from utils.roles.applications.config import get
    from utils.roles.applications.services.database import (
        get_database_service_config,
        resolve_database_service_key,
    )
    from utils.roles.applications.services.sso import get_sso_config


def _to_plain(obj: Any) -> Any:
    """Convert Ansible/Jinja proxy types into plain Python so PyYAML can serialize."""

    if obj is None:
        return None

    # Cast string-like to built-in str: PyYAML cannot represent Ansible proxy types.
    if isinstance(obj, str):
        return str(obj)

    if isinstance(obj, (int, float, bool)):
        return obj

    if isinstance(obj, Mapping):
        return {str(_to_plain(k)): _to_plain(v) for k, v in obj.items()}

    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [_to_plain(x) for x in obj]

    return str(obj)


def _resolve_database_volume_name(
    applications: dict[str, Any], application_id: str, dbtype: str
) -> str:
    """Mirror `plugins/lookup/database.py`'s `volume_prefix + host` derivation
    so callers no longer thread `lookup('database', ..., 'volume')` through
    every `compose.yml.j2`."""
    consumer_entity = get_entity_name(application_id)
    db_id = f"svc-db-{dbtype}"
    central_name = get(
        applications=applications,
        application_id=db_id,
        config_path=f"services.{dbtype}.name",
        strict=False,
        default="",
        skip_missing_app=True,
    )
    central_name = (str(central_name) if central_name is not None else "").strip()
    service_cfg = get_database_service_config(applications, application_id)
    central_enabled = bool(service_cfg.get("shared", False))
    host = central_name if central_enabled else "database"
    volume_prefix = "" if central_enabled else f"{consumer_entity}_"
    return f"{volume_prefix}{host}"


def compose_volumes(
    applications: dict[str, Any],
    application_id: str,
    *,
    extra_volumes: dict[str, dict[str, Any]] | None = None,
) -> str:
    """
    Builds the top-level `volumes:` section for compose.

    Logic is identical to roles/sys-svc-compose/templates/volumes.yml.j2:

      - database volume if:
          a direct mariadb/postgres service is enabled
          and that service is not shared

        name: derived from the central provider's `services.<dbtype>.name`
        when `shared=true`, or `<consumer-entity>_database` when the role
        ships a dedicated instance. The volume name is always derived from
        the applications config — callers MUST NOT thread it in manually.

      - redis volume if:
          is_docker_service_enabled(redis)
          or (services.sso.enabled AND services.sso.flavor == 'oauth2')

        The SSO-proxy sidecar uses redis as its session store; only the
        oauth2 flavor pulls it in. Pure-OIDC roles do NOT need redis.

        name: {{ application_id | get_entity_name }}_redis

    Manual volumes can be appended via extra_volumes (like adding YAML lines after an include).

    TODO: simultaneous postgres + mariadb on a single role is rejected
    by `resolve_database_service_key` (the embedded service templates
    both use the `database` service key + host, which would collide).
    Support is deferred — when a future architecture rewrite gives each
    dbtype its own service / host / volume key, this filter MUST emit
    one volume entry per enabled dbtype.
    """

    if applications is None:
        raise AnsibleFilterError("compose_volumes: 'applications' must not be None")
    if not isinstance(applications, dict):
        raise AnsibleFilterError("compose_volumes: 'applications' must be a dict")
    if not application_id or not isinstance(application_id, str):
        raise AnsibleFilterError(
            "compose_volumes: 'application_id' must be a non-empty string"
        )
    if application_id not in applications:
        raise AnsibleFilterError(
            f"compose_volumes: unknown application_id '{application_id}'"
        )

    volumes: dict[str, Any] = {}

    try:
        database_service_key = resolve_database_service_key(
            applications, application_id
        )
    except ValueError as exc:
        raise AnsibleFilterError(
            "compose_volumes: "
            f"{exc}. Simultaneous postgres + mariadb on the same role "
            "is not supported (the embedded service templates collide "
            "on the `database` service key, host name, and volume "
            "key); pick one dbtype per role. Future support is tracked "
            "in the filter's docstring TODO."
        ) from exc
    database_service = get_database_service_config(applications, application_id)
    database_needed = bool(database_service_key) and not bool(
        database_service.get("shared", False)
    )

    if database_needed:
        volumes["database"] = {
            "name": _resolve_database_volume_name(
                applications, application_id, database_service_key
            )
        }

    for engine in ("seaweedfs", "minio"):
        engine_enabled = bool(
            get(
                applications=applications,
                application_id=application_id,
                config_path=f"services.{engine}.enabled",
                strict=False,
                default=False,
            )
        )
        engine_shared = bool(
            get(
                applications=applications,
                application_id=application_id,
                config_path=f"services.{engine}.shared",
                strict=False,
                default=False,
            )
        )
        if engine_enabled and not engine_shared:
            volumes[engine] = {"name": f"{get_entity_name(application_id)}_{engine}"}

    sso = get_sso_config(applications, application_id)

    if (
        _DockerServiceEnabledFilter.is_docker_service_enabled(
            applications, application_id, "redis"
        )
        or sso["is_proxy_gated"]
    ):
        volumes["redis"] = {"name": f"{get_entity_name(application_id)}_redis"}

    if extra_volumes:
        volumes.update(extra_volumes)

    payload = {"volumes": _to_plain(volumes)}

    return dump_yaml_str(payload).rstrip()


class FilterModule:
    def filters(self):
        return {"compose_volumes": compose_volumes}
