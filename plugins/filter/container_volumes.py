"""Render the per-service ``volumes:`` / ``configs:`` / ``secrets:`` block
for one compose service, fed from the role's ``meta/volumes.yml``.

The output starts at column 0; the caller is responsible for indenting
it with ``| indent(4)`` (or whatever depth) so the block sits under the
right service in ``compose.yml.j2``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleFilterError, AnsibleUndefinedVariable

from utils.cache.yaml import dump_yaml_str

if TYPE_CHECKING:
    from collections.abc import Callable

from utils.cache.applications import get_canonical_volumes
from utils.roles.applications.mounts import (
    mount_default_read_only,
    mount_when_passes,
    normalize_volumes_meta,
)


def _coerce_mode_int(value: Any) -> int:
    if isinstance(value, bool):
        raise AnsibleFilterError(
            f"container_volumes: mode must be an octal int or string, got bool: {value!r}"
        )
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        raise AnsibleFilterError("container_volumes: mode is empty")
    try:
        return int(text, 8)
    except ValueError as exc:
        raise AnsibleFilterError(
            f"container_volumes: mode {value!r} is not a valid octal: {exc}"
        ) from exc


def _short_form_volume(source_name: str, target: str, read_only: bool) -> str:
    suffix = ":ro" if read_only else ""
    return f"{source_name}:{target}{suffix}"


def container_volumes(
    applications: dict[str, Any],
    application_id: str,
    service: str,
    *,
    extra_volumes: list[Any] | None = None,
    extra_configs: list[dict[str, Any]] | None = None,
    extra_secrets: list[dict[str, Any]] | None = None,
    render_jinja: Callable[[str], str] | None = None,
) -> str:
    """Return the per-service mount block (``volumes:`` + ``configs:`` +
    ``secrets:``) as a YAML string starting at column 0.
    """
    if not isinstance(applications, dict):
        raise AnsibleFilterError("container_volumes: 'applications' must be a dict")
    if not isinstance(application_id, str) or not application_id.strip():
        raise AnsibleFilterError(
            "container_volumes: 'application_id' must be a non-empty string"
        )
    if not isinstance(service, str) or not service.strip():
        raise AnsibleFilterError(
            "container_volumes: 'service' must be a non-empty string"
        )

    role_data = applications.get(application_id) or {}
    raw_meta_volumes = (
        get_canonical_volumes(application_id) or role_data.get("volumes") or {}
    )
    canonical_entries = normalize_volumes_meta(raw_meta_volumes)

    volumes_block: list[Any] = []
    configs_block: list[dict[str, Any]] = []
    secrets_block: list[dict[str, Any]] = []

    for semantic_name, entry in canonical_entries.items():
        vtype = entry.get("type", "volume")
        volume_level_ro = bool(entry.get("read_only", mount_default_read_only(entry)))

        for mount in entry.get("mounts") or []:
            if not isinstance(mount, dict):
                continue
            if mount.get("service") != service:
                continue
            if not mount_when_passes(mount, render_jinja):
                continue

            target = mount.get("target")
            if not target:
                continue
            target_text = str(target)
            if render_jinja is not None and (
                "{{" in target_text or "{%" in target_text
            ):
                try:
                    target = str(render_jinja(target_text))
                except AnsibleUndefinedVariable as exc:
                    raise AnsibleFilterError(
                        f"container_volumes: failed to render mount target "
                        f"{target_text!r} for application {application_id!r}, "
                        f"service {service!r}: {exc}"
                    ) from exc

            if vtype == "volume":
                read_only = bool(mount.get("read_only", volume_level_ro))
                volumes_block.append(
                    _short_form_volume(semantic_name, target, read_only)
                )

            elif vtype == "bind":
                source = str(entry.get("source", ""))
                if render_jinja is not None and ("{{" in source or "{%" in source):
                    try:
                        source = str(render_jinja(source))
                    except AnsibleUndefinedVariable as exc:
                        raise AnsibleFilterError(
                            f"container_volumes: failed to render bind source "
                            f"{source!r} for application {application_id!r}, "
                            f"service {service!r}: {exc}"
                        ) from exc
                read_only = bool(mount.get("read_only", volume_level_ro))
                volumes_block.append(_short_form_volume(source, target, read_only))

            elif vtype == "tmpfs":
                tmpfs_entry: dict[str, Any] = {
                    "type": "tmpfs",
                    "target": target,
                }
                if mount.get("size") is not None:
                    tmpfs_entry["tmpfs"] = {"size": mount["size"]}
                volumes_block.append(tmpfs_entry)

            elif vtype == "config":
                cfg_ref: dict[str, Any] = {"source": semantic_name, "target": target}
                mode_value = entry.get("mode")
                if mode_value:
                    cfg_ref["mode"] = _coerce_mode_int(mode_value)
                configs_block.append(cfg_ref)

            elif vtype == "secret":
                sec_ref: dict[str, Any] = {"source": semantic_name, "target": target}
                mode_value = entry.get("mode")
                if mode_value:
                    sec_ref["mode"] = _coerce_mode_int(mode_value)
                secrets_block.append(sec_ref)

    if extra_volumes:
        volumes_block.extend(extra_volumes)
    if extra_configs:
        configs_block.extend(extra_configs)
    if extra_secrets:
        secrets_block.extend(extra_secrets)

    payload: dict[str, Any] = {}
    if volumes_block:
        payload["volumes"] = volumes_block
    if configs_block:
        payload["configs"] = configs_block
    if secrets_block:
        payload["secrets"] = secrets_block

    if not payload:
        return ""

    return dump_yaml_str(payload).rstrip()
