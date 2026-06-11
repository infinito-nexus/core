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


def _swarm_nfs_driver_opts(dir_var_lib: str, volume_name: str) -> dict[str, Any]:
    # Bind from host's already-NFS-mounted DIR_VAR_LIB; Docker's `type: nfs`
    # would re-handshake portmap, which is unreachable in nested DinD.
    return {
        "driver": "local",
        "driver_opts": {
            "type": "none",
            "o": "bind",
            "device": f"{dir_var_lib.rstrip('/')}/{volume_name}",
        },
    }


def compose_volumes(
    applications: dict[str, Any],
    application_id: str,
    *,
    extra_volumes: dict[str, dict[str, Any]] | None = None,
    deployment_mode: str = "compose",
    storage: dict[str, Any] | None = None,
    dir_var_lib: str,
) -> str:
    """Render the top-level `volumes:` section for compose or swarm."""

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
            "key); pick one dbtype per role."
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

    meta_volumes = applications.get(application_id, {}).get("volumes") or {}
    nfs_keys = {
        k
        for k, v in meta_volumes.items()
        if isinstance(v, dict) and v.get("nfs") is not None
    }

    storage_backend = (storage or {}).get("backend", "local")
    swarm_nfs_enabled = (
        deployment_mode == "swarm" and str(storage_backend).lower() == "nfs"
    )

    for vol_name, vol_spec in list(volumes.items()):
        if not isinstance(vol_spec, dict):
            continue
        wants_nfs = bool(vol_spec.pop("nfs", False)) or (vol_name in nfs_keys)
        if wants_nfs and swarm_nfs_enabled:
            named = vol_spec.get("name", vol_name)
            vol_spec.update(_swarm_nfs_driver_opts(dir_var_lib, str(named)))

    payload = {"volumes": _to_plain(volumes)}

    return dump_yaml_str(payload).rstrip()
