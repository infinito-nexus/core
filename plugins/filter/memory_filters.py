from __future__ import annotations

import re
from ansible.errors import AnsibleFilterError
from utils.applications.config import get
from utils.entity_name_utils import get_entity_name

# Regex and unit conversion table
_UNIT_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kKmMgGtT]?[bB]?)?\s*$")
_FACTORS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "m": 1024**2,
    "mb": 1024**2,
    "g": 1024**3,
    "gb": 1024**3,
    "t": 1024**4,
    "tb": 1024**4,
}

# ------------------------------------------------------
# Helpers: unit conversion
# ------------------------------------------------------


def _to_bytes(v: str) -> int:
    """Convert a human-readable size string (e.g., '2g', '512m') to bytes."""
    if v is None:
        raise AnsibleFilterError("memory_filters: size value is None")

    s = str(v).strip()
    m = _UNIT_RE.match(s)
    if not m:
        raise AnsibleFilterError(f"memory_filters: invalid size '{v}'")

    num, unit = m.group(1), (m.group(2) or "").lower()

    try:
        val = float(num)
    except ValueError as e:
        raise AnsibleFilterError(f"memory_filters: invalid numeric size '{v}'") from e

    factor = _FACTORS.get(unit)
    if factor is None:
        raise AnsibleFilterError(f"memory_filters: unknown unit in '{v}'")

    return int(val * factor)


def _to_mb(v: str) -> int:
    """Convert human-readable size to megabytes."""
    return max(0, _to_bytes(v) // (1024 * 1024))


# ------------------------------------------------------
# JVM-specific helpers
# ------------------------------------------------------


def _svc(app_id: str) -> str:
    """Resolve the internal service name for JVM-based applications."""
    return get_entity_name(app_id)


def _mem_limit_mb(apps: dict, app_id: str) -> int:
    """Resolve mem_limit for the JVM service of the given application."""
    svc = _svc(app_id)
    raw = get(apps, app_id, f"services.{svc}.mem_limit")
    mb = _to_mb(raw)

    if mb <= 0:
        raise AnsibleFilterError(
            f"memory_filters: mem_limit for '{svc}' must be > 0 MB (got '{raw}')"
        )
    return mb


def _mem_res_mb(apps: dict, app_id: str) -> int:
    """Resolve mem_reservation for the JVM service of the given application."""
    svc = _svc(app_id)
    raw = get(apps, app_id, f"services.{svc}.mem_reservation")
    mb = _to_mb(raw)

    if mb <= 0:
        raise AnsibleFilterError(
            f"memory_filters: mem_reservation for '{svc}' must be > 0 MB (got '{raw}')"
        )
    return mb


def jvm_max_mb(apps: dict, app_id: str) -> int:
    """
    Compute recommended JVM Xmx in MB using:
    Xmx = min(
        floor(0.7 * mem_limit),
        mem_limit - 1024,
        12288
    )
    with a lower bound of 1024 MB.
    """
    limit_mb = _mem_limit_mb(apps, app_id)
    c1 = (limit_mb * 7) // 10
    c2 = max(0, limit_mb - 1024)
    c3 = 12288

    return max(1024, min(c1, c2, c3))


def jvm_min_mb(apps: dict, app_id: str) -> int:
    """
    Compute recommended JVM Xms in MB using:
    Xms = min(
        floor(Xmx / 2),
        mem_reservation,
        Xmx
    )
    with a lower bound of 512 MB.
    """
    xmx = jvm_max_mb(apps, app_id)
    res = _mem_res_mb(apps, app_id)

    return max(512, min(xmx // 2, res, xmx))


# ------------------------------------------------------
# Redis-specific helpers (always service name "redis")
# ------------------------------------------------------


def _redis_mem_limit_mb(apps: dict, app_id: str, default_mb: int = 256) -> int:
    """
    Resolve mem_limit for the Redis service of an application.
    Unlike JVM-based services, Redis always uses the service name "redis".

    If no mem_limit is defined, fall back to default_mb.
    """
    raw = get(
        apps,
        app_id,
        "services.redis.mem_limit",
        strict=False,
        default=f"{default_mb}m",
    )

    mb = _to_mb(raw)

    if mb <= 0:
        raise AnsibleFilterError(
            f"memory_filters: mem_limit for 'redis' must be > 0 MB (got '{raw}')"
        )

    return mb


def redis_maxmemory_mb(
    apps: dict, app_id: str, factor: float = 0.8, min_mb: int = 64
) -> int:
    """
    Compute recommended Redis `maxmemory` in MB.

    * factor: fraction of allowed memory used for Redis data (default 0.8)
    * min_mb: minimum floor value (default 64 MB)

    maxmemory = max(min_mb, floor(factor * mem_limit))
    """
    limit_mb = _redis_mem_limit_mb(apps, app_id)
    return max(min_mb, int(limit_mb * factor))


# ------------------------------------------------------
# Filter module
# ------------------------------------------------------


class FilterModule(object):
    def filters(self):
        return {
            "jvm_max_mb": jvm_max_mb,
            "jvm_min_mb": jvm_min_mb,
            "redis_maxmemory_mb": redis_maxmemory_mb,
        }
