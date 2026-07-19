from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import dump_yaml_str

try:
    from plugins.filter.docker.service_enabled import (
        FilterModule as _DockerServiceEnabledFilter,
    )
    from plugins.filter.get.entity_name import get_entity_name
    from utils.cache.applications import get_canonical_volumes
    from utils.roles.applications.config import get
    from utils.roles.applications.mounts import (
        content_hash,
        mount_when_passes,
        normalize_volumes_meta,
    )
    from utils.roles.applications.services.database import (
        get_database_service_config,
        resolve_database_service_key,
    )
    from utils.roles.applications.services.sso import get_sso_config
    from utils.roles.meta_lookup import get_role_placement
except ModuleNotFoundError:
    from docker.service_enabled import FilterModule as _DockerServiceEnabledFilter
    from get.entity_name import get_entity_name

    from utils.cache.applications import get_canonical_volumes
    from utils.roles.applications.config import get
    from utils.roles.applications.mounts import (
        content_hash,
        mount_when_passes,
        normalize_volumes_meta,
    )
    from utils.roles.applications.services.database import (
        get_database_service_config,
        resolve_database_service_key,
    )
    from utils.roles.applications.services.sso import get_sso_config
    from utils.roles.meta_lookup import get_role_placement


def _to_plain(obj: Any) -> Any:
    """Convert Ansible/Jinja proxy types into plain Python so PyYAML can serialize."""

    if obj is None:
        return None

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
    return {
        "driver": "local",
        "driver_opts": {
            "type": "none",
            "o": "bind",
            "device": f"{dir_var_lib.rstrip('/')}/{volume_name}",
        },
    }


def _read_file_for_hash(source: str) -> str:
    """Read a file's content for hash-based naming. Returns the path as a
    stable fallback when the file isn't materialised yet (lint runs)."""
    try:
        from utils.cache.files import read_text

        return read_text(source)
    except (OSError, ValueError):
        return source


def _config_secret_name(role_entity: str, user_name: str, source: str) -> str:
    """Build a swarm-rotation-safe name: ``{role}_{name}_{sha8(content)}``."""
    digest = content_hash(_read_file_for_hash(source))
    return f"{role_entity}_{user_name}_{digest}"


def _maybe_render(value: Any, render_jinja: Any) -> str:
    text = str(value)
    if render_jinja is None or ("{{" not in text and "{%" not in text):
        return text
    try:
        return str(render_jinja(text))
    except Exception:
        return text


def compose_volumes(
    applications: dict[str, Any],
    application_id: str,
    *,
    extra_volumes: dict[str, dict[str, Any]] | None = None,
    extra_configs: dict[str, dict[str, Any]] | None = None,
    extra_secrets: dict[str, dict[str, Any]] | None = None,
    deployment_mode: str = "compose",
    storage: dict[str, Any] | None = None,
    dir_var_lib: str,
    render_jinja: Any = None,
) -> str:
    """Render the top-level ``volumes:`` / ``configs:`` / ``secrets:`` block.

    Reads the canonical dict-of-dicts shape from
    ``roles/<role>/meta/volumes.yml`` (YAML key = semantic short name;
    optional ``name:`` field = docker volume name). Entries with
    ``type: config`` / ``type: secret`` emit their respective top-level
    sections; everything else flows through the volumes section.

    A ``type: volume`` entry may set ``nfs: false`` to opt out of the
    swarm NFS rewrite: the volume then stays a plain node-local named
    volume even when ``storage.backend`` is ``nfs`` (e.g. gitaly
    repository storage, which upstream forbids on NFS). Any other
    ``nfs`` value (absent, ``true``, or the uid/gid/mode dict consumed
    by the NFS subdir pre-creation) keeps the rewrite.
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

    role_entity = get_entity_name(application_id)
    volumes: dict[str, Any] = {}
    configs: dict[str, Any] = {}
    secrets: dict[str, Any] = {}

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
        volumes["redis"] = {"name": f"{role_entity}_redis"}

    if extra_volumes:
        volumes.update(extra_volumes)
    if extra_configs:
        configs.update(extra_configs)
    if extra_secrets:
        secrets.update(extra_secrets)

    role_data = applications.get(application_id) or {}
    raw_meta_volumes = (
        get_canonical_volumes(application_id) or role_data.get("volumes") or {}
    )
    canonical_entries = normalize_volumes_meta(raw_meta_volumes)

    for semantic_name, entry in canonical_entries.items():
        vtype = entry.get("type", "volume")

        if vtype == "volume":
            if semantic_name in volumes:
                continue
            spec: dict[str, Any] = {}
            docker_name = entry.get("name")
            if docker_name:
                spec["name"] = docker_name
            if "nfs" in entry:
                spec["nfs"] = entry["nfs"]
            volumes[semantic_name] = spec
            continue

        if vtype in ("config", "secret") and not any(
            mount_when_passes(mount, render_jinja)
            for mount in entry.get("mounts") or []
            if isinstance(mount, dict)
        ):
            continue

        if vtype == "config":
            source = _maybe_render(entry.get("source", ""), render_jinja)
            configs[semantic_name] = {
                "name": _maybe_render(entry.get("name", ""), render_jinja)
                or _config_secret_name(role_entity, semantic_name, source),
                "file": source,
            }
            continue

        if vtype == "secret":
            source = _maybe_render(entry.get("source", ""), render_jinja)
            secrets[semantic_name] = {
                "name": _maybe_render(entry.get("name", ""), render_jinja)
                or _config_secret_name(role_entity, semantic_name, source),
                "file": source,
            }
            continue

    storage_backend = (storage or {}).get("backend", "local")
    swarm_nfs_enabled = (
        deployment_mode == "swarm" and str(storage_backend).lower() == "nfs"
    )
    role_pinned = (
        str(get_role_placement(application_id) or "").strip().lower() == "manager"
    )

    for vol_name, vol_spec in list(volumes.items()):
        if not isinstance(vol_spec, dict):
            continue
        nfs_meta = vol_spec.pop("nfs", None)
        nfs_opted_out = nfs_meta is False
        if swarm_nfs_enabled and not role_pinned and not nfs_opted_out:
            named = vol_spec.get("name", vol_name)
            vol_spec.update(_swarm_nfs_driver_opts(dir_var_lib, str(named)))
            if isinstance(nfs_meta, dict):
                vol_spec["x-infinito-nfs"] = dict(nfs_meta)

    payload: dict[str, Any] = {"volumes": _to_plain(volumes)}
    if configs:
        payload["configs"] = _to_plain(configs)
    if secrets:
        payload["secrets"] = _to_plain(secrets)

    return dump_yaml_str(payload).rstrip()
