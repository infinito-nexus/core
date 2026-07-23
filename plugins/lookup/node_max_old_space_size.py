"""Derive a Node.js ``--max-old-space-size`` (MB) from a service's mem_limit.

Lookup form — the app config is resolved internally, so callers no longer pipe
``lookup('applications')`` in:

    {{ lookup('node_max_old_space_size', application_id, service_name) }}
    {{ lookup('node_max_old_space_size', application_id, service_name,
              pct=0.125, min_mb=256, hardcap_mb=1024) }}

Heuristics (defaults):
  - candidate = 35% of mem_limit
  - min       = 768 MB (required minimum)
  - cap       = min(3072 MB, 60% of mem_limit)

If mem_limit (container cgroup RAM) is smaller than ``min_mb`` an exception is
raised, to prevent Node's heap from exceeding the cgroup and being OOM-killed.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import AppConfigKeyError, get
from utils.sizes import to_bytes


def _mb(bytes_val: int) -> int:
    """Return decimal MB (10^6) as integer — Node expects MB units."""
    return round(bytes_val / 10**6)


def _compute_old_space_mb(
    total_mb: int, pct: float, min_mb: int, hardcap_mb: int, safety_cap_pct: float
) -> int:
    """Compute Node.js old-space heap (MB) with safe minimum and cap handling.

    NOTE: The caller ensures total_mb >= min_mb; here we only apply the sizing
    heuristics and caps."""
    candidate = int(total_mb * float(pct))
    safety_cap = int(total_mb * float(safety_cap_pct))
    final_cap = min(int(hardcap_mb), safety_cap)

    candidate = max(candidate, int(min_mb))
    if final_cap >= int(min_mb):
        candidate = min(candidate, final_cap)

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
    """Derive Node.js --max-old-space-size (MB) from services.<service>.mem_limit.

    Raises AnsibleError if mem_limit is missing/invalid OR if mem_limit (MB) < min_mb.
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
        raise AnsibleError(str(e)) from e

    if mem_limit in (None, False, ""):
        raise AnsibleError(
            f"mem_limit not set for application '{application_id}', service '{service_name}'"
        )

    total_mb = _mb(to_bytes(mem_limit))

    if total_mb < int(min_mb):
        raise AnsibleError(
            f"mem_limit ({total_mb} MB) is below the required minimum heap ({int(min_mb)} MB) "
            f"for application '{application_id}', service '{service_name}'. "
            f"Increase mem_limit or lower min_mb."
        )

    return _compute_old_space_mb(total_mb, pct, min_mb, hardcap_mb, safety_cap_pct)


class LookupModule(LookupBase):
    """lookup('node_max_old_space_size', application_id, service_name[, pct=, min_mb=, hardcap_mb=, safety_cap_pct=])"""

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms) != 2:
            raise AnsibleError(
                "lookup('node_max_old_space_size', application_id, service_name"
                "[, pct=, min_mb=, hardcap_mb=, safety_cap_pct=]) expects exactly "
                "2 positional terms."
            )
        application_id, service_name = terms[0], terms[1]

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=variables)[0]

        return [
            node_max_old_space_size(
                applications,
                application_id,
                service_name,
                pct=float(kwargs.get("pct", 0.35)),
                min_mb=int(kwargs.get("min_mb", 768)),
                hardcap_mb=int(kwargs.get("hardcap_mb", 3072)),
                safety_cap_pct=float(kwargs.get("safety_cap_pct", 0.60)),
            )
        ]
