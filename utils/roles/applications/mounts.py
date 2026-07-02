"""Normalize and validate the role-level mount declaration in
``roles/<role>/meta/volumes.yml``.

Canonical shape (dict-of-dicts; the YAML key is the semantic short name):

    data:                               # YAML key = semantic short name
      type: volume                      # bind | volume | config | secret | tmpfs
      name: matrix_synapse_data         # OPTIONAL docker volume name; defaults to the key
      nfs: true                         # only meaningful for type: volume
      mounts:
        - service: synapse
          target: /data
          read_only: false              # per-mount override of volume-level
          when: "{{ FLAG | bool }}"

    config:
      type: bind                        # bind | config | secret may carry source
      source: "{{ FOO }}"
      read_only: true
      mode: "0440"                      # only for config/secret
      mounts:
        - service: synapse
          target: /etc/synapse/config

The legacy list-of-dicts shape is no longer accepted.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterable

_VALID_TYPES = frozenset({"bind", "volume", "config", "secret", "tmpfs"})
_TYPE_REQUIRES_SOURCE = frozenset({"bind", "config", "secret"})
_TYPE_HAS_MODE = frozenset({"config", "secret"})
_TYPE_HAS_READ_ONLY = frozenset({"bind", "volume"})
_TYPE_HAS_NFS = frozenset({"volume"})


class VolumesSchemaError(ValueError):
    """Raised when a meta/volumes.yml fails schema validation."""


def normalize_volumes_meta(
    meta_volumes: Any,
) -> dict[str, dict[str, Any]]:
    """Return a dict[semantic_name -> canonical entry].

    The YAML key is the semantic short name. Each entry value MAY carry
    ``name`` (the docker volume name); when absent and ``type`` is
    ``volume``, callers default the docker name to the semantic key.
    """
    if meta_volumes is None:
        return {}
    if isinstance(meta_volumes, list):
        raise VolumesSchemaError(
            "list-shape meta/volumes.yml is no longer supported; use dict-keyed-by-name"
        )
    if not isinstance(meta_volumes, dict):
        raise VolumesSchemaError(
            f"meta/volumes.yml must be a dict, got {type(meta_volumes).__name__}"
        )
    out: dict[str, dict[str, Any]] = {}
    for semantic_name, raw_spec in meta_volumes.items():
        if not isinstance(semantic_name, str) or not semantic_name.strip():
            raise VolumesSchemaError(
                f"meta/volumes.yml key must be a non-empty string, got {semantic_name!r}"
            )
        if not isinstance(raw_spec, dict):
            raise VolumesSchemaError(
                f"volume entry for {semantic_name!r} must be a dict, "
                f"got {type(raw_spec).__name__}"
            )
        entry = dict(raw_spec)
        entry.setdefault("type", "volume")
        out[semantic_name] = entry
    return out


def validate_volumes_meta(
    meta_volumes: Any,
    role_id: str,
) -> list[str]:
    """Return a list of human-readable violation strings (empty = valid)."""
    violations: list[str] = []
    try:
        entries = normalize_volumes_meta(meta_volumes)
    except VolumesSchemaError as exc:
        return [f"{role_id}: {exc}"]

    for semantic_name, entry in entries.items():
        prefix = f"{role_id} ({semantic_name})"

        if "name" in entry:
            docker_name = entry["name"]
            if not isinstance(docker_name, str) or not docker_name.strip():
                violations.append(
                    f"{prefix}: 'name' (container volume name) must be a non-empty string"
                )

        vtype = entry.get("type", "volume")
        if vtype not in _VALID_TYPES:
            violations.append(
                f"{prefix}: 'type' must be one of {sorted(_VALID_TYPES)}, got {vtype!r}"
            )
            continue

        if vtype in _TYPE_REQUIRES_SOURCE and not entry.get("source"):
            violations.append(f"{prefix}: type '{vtype}' requires a non-empty 'source'")
        if vtype not in _TYPE_REQUIRES_SOURCE and entry.get("source"):
            violations.append(
                f"{prefix}: type '{vtype}' MUST NOT carry 'source' (got {entry['source']!r})"
            )

        if "mode" in entry and vtype not in _TYPE_HAS_MODE:
            violations.append(
                f"{prefix}: 'mode' is only valid for type config/secret (got type={vtype!r})"
            )
        if "mode" in entry and vtype in _TYPE_HAS_MODE:
            mode = entry["mode"]
            if not (
                isinstance(mode, str)
                and mode.startswith("0")
                and mode.lstrip("0").isdigit()
            ):
                violations.append(
                    f"{prefix}: 'mode' must be an octal string like \"0440\", got {mode!r}"
                )

        if "read_only" in entry and vtype not in _TYPE_HAS_READ_ONLY:
            violations.append(
                f"{prefix}: 'read_only' is only valid for type bind/volume (got type={vtype!r})"
            )
        if "read_only" in entry and not isinstance(entry["read_only"], bool):
            violations.append(
                f"{prefix}: 'read_only' must be bool, got {type(entry['read_only']).__name__}"
            )

        if "nfs" in entry and vtype not in _TYPE_HAS_NFS:
            violations.append(
                f"{prefix}: 'nfs' is only valid for type volume (got type={vtype!r})"
            )
        if "nfs" in entry and not isinstance(entry["nfs"], (bool, dict)):
            violations.append(
                f"{prefix}: 'nfs' must be bool or dict, got {type(entry['nfs']).__name__}"
            )

        if "swarm_safe" in entry and vtype != "bind":
            violations.append(
                f"{prefix}: 'swarm_safe' opt-out is only meaningful for type bind "
                f"(got type={vtype!r})"
            )
        if "swarm_safe" in entry and not isinstance(entry["swarm_safe"], bool):
            violations.append(
                f"{prefix}: 'swarm_safe' must be bool, got "
                f"{type(entry['swarm_safe']).__name__}"
            )

        if vtype == "tmpfs":
            violations.extend(
                f"{prefix}: tmpfs 'size' must be a string or int, got "
                f"{type(mount['size']).__name__}"
                for mount in (entry.get("mounts") or [])
                if "size" in mount and not isinstance(mount["size"], (str, int))
            )

        mounts = entry.get("mounts")
        if mounts is None:
            continue
        if not isinstance(mounts, list):
            violations.append(
                f"{prefix}: 'mounts' must be a list, got {type(mounts).__name__}"
            )
            continue
        for midx, mount in enumerate(mounts):
            mprefix = f"{prefix}.mounts[{midx}]"
            if not isinstance(mount, dict):
                violations.append(f"{mprefix}: mount entry must be a dict")
                continue
            if (
                not isinstance(mount.get("service"), str)
                or not mount["service"].strip()
            ):
                violations.append(
                    f"{mprefix}: 'service' is required and must be a non-empty string"
                )
            if not isinstance(mount.get("target"), str) or not mount["target"].strip():
                violations.append(
                    f"{mprefix}: 'target' is required and must be a non-empty string"
                )
            if "read_only" in mount and vtype not in _TYPE_HAS_READ_ONLY:
                violations.append(
                    f"{mprefix}: 'read_only' is only valid for type bind/volume (got type={vtype!r})"
                )
            if "read_only" in mount and not isinstance(mount["read_only"], bool):
                violations.append(
                    f"{mprefix}: 'read_only' must be bool, got {type(mount['read_only']).__name__}"
                )

    return violations


def mount_default_read_only(volume: dict[str, Any]) -> bool:
    """Default read-only policy per type.

    bind/volume default to rw (False); config/secret are conceptually
    read-only at the docker primitive level; tmpfs is rw.
    """
    return volume.get("type", "volume") in _TYPE_HAS_MODE


def content_hash(text: str, length: int = 8) -> str:
    """Stable short hex digest of a string (used for swarm config/secret name rotation)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:length]


def mounts_for_service(
    volume: dict[str, Any], service: str
) -> Iterable[dict[str, Any]]:
    """Yield mount dicts in ``volume['mounts']`` that target ``service``."""
    for mount in volume.get("mounts") or []:
        if isinstance(mount, dict) and mount.get("service") == service:
            yield mount
