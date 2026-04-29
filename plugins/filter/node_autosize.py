# filter_plugins/node_autosize.py
# Reuse app config to derive sensible Node.js heap sizes for containers.
#
# Usage example (Jinja):
#   {{ lookup('applications') | node_max_old_space_size('web-app-nextcloud', 'whiteboard') }}
#
# Heuristics (defaults):
#   - candidate = 35% of mem_limit
#   - min       = 768 MB (required minimum)
#   - cap       = min(3072 MB, 60% of mem_limit)
#
# NEW: If mem_limit (container cgroup RAM) is smaller than min_mb, we raise an
# exception — to prevent a misconfiguration where Node's heap could exceed the cgroup
# and be OOM-killed.

from __future__ import annotations
import re
from ansible.errors import AnsibleFilterError

# Import the shared config resolver from utils
try:
    from utils.applications.config import get, AppConfigKeyError
except Exception as e:
    raise AnsibleFilterError(
        f"Failed to import get from utils.applications.config: {e}"
    )

_SIZE_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([kmgtp]?i?b?)?\s*$", re.IGNORECASE)
_MULT = {
    "": 1,
    "b": 1,
    "k": 10**3,
    "kb": 10**3,
    "m": 10**6,
    "mb": 10**6,
    "g": 10**9,
    "gb": 10**9,
    "t": 10**12,
    "tb": 10**12,
    "p": 10**15,
    "pb": 10**15,
    "kib": 1024,
    "mib": 1024**2,
    "gib": 1024**3,
    "tib": 1024**4,
    "pib": 1024**5,
}


def _to_bytes(val):
    """Convert numeric or string memory limits (e.g. '512m', '2GiB') to bytes."""
    if val is None or val == "":
        return None
    if isinstance(val, (int, float)):
        return int(val)
    if not isinstance(val, str):
        raise AnsibleFilterError(f"Unsupported mem_limit type: {type(val).__name__}")
    m = _SIZE_RE.match(val)
    if not m:
        raise AnsibleFilterError(f"Unrecognized mem_limit string: {val!r}")
    num = float(m.group(1))
    unit = (m.group(2) or "").lower()
    if unit not in _MULT:
        raise AnsibleFilterError(f"Unknown unit in mem_limit: {unit!r}")
    return int(num * _MULT[unit])


def _mb(bytes_val: int) -> int:
    """Return decimal MB (10^6) as integer — Node expects MB units."""
    return int(round(bytes_val / 10**6))


def _compute_old_space_mb(
    total_mb: int, pct: float, min_mb: int, hardcap_mb: int, safety_cap_pct: float
) -> int:
    """
    Compute Node.js old-space heap (MB) with safe minimum and cap handling.

    NOTE: The calling function ensures total_mb >= min_mb; here we only
    apply the sizing heuristics and caps.
    """
    candidate = int(total_mb * float(pct))
    safety_cap = int(total_mb * float(safety_cap_pct))
    final_cap = min(int(hardcap_mb), safety_cap)

    # Enforce minimum first; only apply cap if it's above the minimum
    candidate = max(candidate, int(min_mb))
    if final_cap >= int(min_mb):
        candidate = min(candidate, final_cap)

    # Never below a tiny hard floor
    return max(candidate, 128)


def node_max_old_space_size(
    applications: dict,
    application_id: str,
    service_name: str,
    pct: float = 0.35,
    min_mb: int = 768,
    hardcap_mb: int = 3072,
    safety_cap_pct: float = 0.60,
) -> int:
    """
    Derive Node.js --max-old-space-size (MB) from the service's mem_limit in app config.

    Looks up: services.<service_name>.mem_limit for the given application_id.

    Raises:
        AnsibleFilterError if mem_limit is missing/invalid OR if mem_limit (MB) < min_mb.
    """
    try:
        mem_limit = get(
            applications=applications,
            application_id=application_id,
            config_path=f"services.{service_name}.mem_limit",
            strict=True,
            default=None,
        )
    except AppConfigKeyError as e:
        raise AnsibleFilterError(str(e))

    if mem_limit in (None, False, ""):
        raise AnsibleFilterError(
            f"mem_limit not set for application '{application_id}', service '{service_name}'"
        )

    total_bytes = _to_bytes(mem_limit)
    total_mb = _mb(total_bytes)

    # NEW: guardrail — refuse to size a heap larger than the cgroup limit
    if total_mb < int(min_mb):
        raise AnsibleFilterError(
            f"mem_limit ({total_mb} MB) is below the required minimum heap ({int(min_mb)} MB) "
            f"for application '{application_id}', service '{service_name}'. "
            f"Increase mem_limit or lower min_mb."
        )

    return _compute_old_space_mb(total_mb, pct, min_mb, hardcap_mb, safety_cap_pct)


class FilterModule(object):
    def filters(self):
        return {
            "node_max_old_space_size": node_max_old_space_size,
        }
