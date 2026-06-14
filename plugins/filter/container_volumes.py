"""Render the per-service ``volumes:`` / ``configs:`` / ``secrets:`` block
for one compose service, fed from the role's ``meta/volumes.yml``.

The output starts at column 0; the caller is responsible for indenting
it with ``| indent(4)`` (or whatever depth) so the block sits under the
right service in ``compose.yml.j2``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleFilterError

from utils.cache.yaml import dump_yaml_str

if TYPE_CHECKING:
    from collections.abc import Callable

from utils.cache.applications import get_canonical_volumes
from utils.roles.applications.mounts import (
    mount_default_read_only,
    normalize_volumes_meta,
)


def _mount_when_passes(
    mount: dict[str, Any], render_jinja: Callable[[str], str] | None
) -> bool:
    when = mount.get("when")
    if when is None:
        return True
    if isinstance(when, bool):
        return when
    text = str(when).strip()
    if not text:
        return True
    if "{{" not in text and "{%" not in text:
        return text.lower() not in {"false", "no", "0", "off"}
    # Treat any render failure as "skip" so we never emit half-resolved
    # expressions downstream.
    if render_jinja is None:
        return False
    try:
        rendered = render_jinja(text)
    except Exception:
        return False
    if isinstance(rendered, bool):
        return rendered
    return str(rendered).strip().lower() not in {"false", "no", "0", "off", ""}


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

    volumes_block: list[Any] = []  # str (short form) | dict (long form tmpfs)
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
            if not _mount_when_passes(mount, render_jinja):
                continue

            target = mount.get("target")
            if not target:
                continue

            if vtype == "volume":
                read_only = bool(mount.get("read_only", volume_level_ro))
                volumes_block.append(
                    _short_form_volume(semantic_name, target, read_only)
                )

            elif vtype == "bind":
                source = str(entry.get("source", ""))
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
                if entry.get("mode"):
                    cfg_ref["mode"] = entry["mode"]
                configs_block.append(cfg_ref)

            elif vtype == "secret":
                sec_ref: dict[str, Any] = {"source": semantic_name, "target": target}
                if entry.get("mode"):
                    sec_ref["mode"] = entry["mode"]
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
