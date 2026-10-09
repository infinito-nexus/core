from __future__ import annotations

import os
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.filter.active_docker import active_docker_container_count
from plugins.filter.split_postgres_connections import split_postgres_connections
from utils.cache.errors import UnresolvableValueError
from utils.env.runtime import mem_total_mb

_CPUS_OVERRIDE = "RESOURCE_HOST_CPUS_OVERRIDE"
_MEM_MB_OVERRIDE = "RESOURCE_HOST_MEM_MB_OVERRIDE"

_HOST_RESERVE_CPU = 2
_HOST_RESERVE_MEM = 4
_PIDS_LIMIT = 512
_POSTGRES_SUPERUSER_RESERVED_CONNECTIONS = 3
_POSTGRES_DELAY = 2
_POSTGRES_MAX_LOCKS_PER_TRANSACTION = 256

_CONTAINER_PREFIX_REGEX = r"^(web-|svc-).*"

_VALUES_CACHE: dict[tuple[int, int, int | None, str], dict[str, Any]] = {}

_SHARE_KEYS = frozenset(
    {
        "active_docker_container_count",
        "cpus",
        "cpus_num",
        "mem_limit",
        "mem_limit_num",
        "mem_reservation",
        "mem_reservation_num",
    }
)


def _round_half_up(value: float, digits: int) -> float:
    """Jinja's ``round`` rounds half away from zero, Python's rounds to even.

    The two disagree on every exact .5, so the port would silently resize
    containers on those hosts without this.
    """
    quantum = Decimal(1).scaleb(-digits)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _positive_int(value: Any) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


class _HostResources:
    """The two measured values, resolved once per lookup call."""

    def __init__(self, variables: dict[str, Any]) -> None:
        self._vars = variables
        self._facts = variables.get("ansible_facts") or {}

    def _is_local_target(self) -> bool:
        return self._vars.get("ansible_connection") == "local"

    def _unmeasurable(self, message: str) -> Exception:
        """The error class, chosen by whether a host is being deployed.

        A play carries `inventory_hostname`, and there a value nobody could
        measure has to stop the run: `UnresolvableValueError` is the one class
        the render layers re-raise instead of swallowing.

        Static renders carry no host. The inventory generator and the lint suite
        both walk the whole applications payload without deploying anything, and
        the meta files of nextcloud and svc-opt-swapfile sit in that payload.
        Aborting there would fail tooling over a value it never reads, so the
        error stays an ordinary `AnsibleError` that best-effort rendering
        absorbs, exactly as the missing fact did before.
        """
        if self._vars.get("inventory_hostname"):
            return UnresolvableValueError(message)
        return AnsibleError(message)

    def _resolve(
        self,
        override_key: str,
        fact_key: str,
        probe: Any,
        unit: str,
    ) -> int:
        override = _positive_int(self._vars.get(override_key))
        if override is not None:
            return override

        from_fact = _positive_int(self._facts.get(fact_key))
        if from_fact is not None:
            return from_fact

        if not self._is_local_target():
            raise self._unmeasurable(
                f"resource: cannot determine the host {unit} of "
                f"'{self._vars.get('inventory_hostname', '<unknown host>')}'. "
                f"Its hardware facts are missing and the probe would measure the "
                f"Ansible controller instead of that host. "
                f"Set '{override_key}: <{unit}>' in the inventory."
            )

        measured = _positive_int(probe())
        if measured is None:
            raise self._unmeasurable(
                f"resource: probing the host {unit} returned no usable value. "
                f"Set '{override_key}: <{unit}>' in the inventory."
            )
        return measured

    @property
    def cpus(self) -> int:
        return self._resolve(_CPUS_OVERRIDE, "processor_vcpus", os.cpu_count, "CPUs")

    @property
    def mem_mb(self) -> int:
        return self._resolve(_MEM_MB_OVERRIDE, "memtotal_mb", mem_total_mb, "MiB")


def _container_count(variables: dict[str, Any]) -> int:
    return active_docker_container_count(
        variables.get("applications") or {},
        variables.get("group_names") or [],
        _CONTAINER_PREFIX_REGEX,
        ensure_min_one=True,
    )


def _build(
    variables: dict[str, Any],
    roles_dir: Path,
    containers: int | None,
) -> dict[str, Any]:
    """Values for one host.

    `containers` stays None unless a requested key needs it. Reading
    `applications` pulls the whole merged payload through the templar, and the
    meta files of nextcloud and svc-opt-swapfile read their memory back out of
    this very lookup, so computing it unconditionally would make that render
    re-enter itself.
    """
    host = _HostResources(variables)
    host_cpus = host.cpus
    host_mem_mb = host.mem_mb

    cache_key = (host_cpus, host_mem_mb, containers, str(roles_dir))
    cached = _VALUES_CACHE.get(cache_key)
    if cached is not None:
        return cached

    host_mem_gb = host_mem_mb // 1024

    avail_cpus = host_cpus - _HOST_RESERVE_CPU
    avail_mem = host_mem_gb - _HOST_RESERVE_MEM

    max_connections = min(host_cpus * 30 + 50, 400)
    shared_buffers_mb = host_mem_mb * 25 // 100
    work_mem_mb = max(host_mem_mb // max(max_connections, 1) // 2, 1)
    maintenance_work_mem_mb = max(host_mem_mb * 5 // 100, 64)

    values = {
        "host_cpus": host_cpus,
        "host_mem_mb": host_mem_mb,
        "host_mem": host_mem_gb,
        "host_reserve_cpu": _HOST_RESERVE_CPU,
        "host_reserve_mem": _HOST_RESERVE_MEM,
        "avail_cpus": avail_cpus,
        "avail_mem": avail_mem,
        "pids_limit": _PIDS_LIMIT,
        "postgres_vcpus": host_cpus,
        "postgres_total_ram_mb": host_mem_mb,
        "postgres_max_connections": max_connections,
        "postgres_allowed_avg_connections": int(
            split_postgres_connections(max_connections, str(roles_dir))
        ),
        "postgres_superuser_reserved_connections": (
            _POSTGRES_SUPERUSER_RESERVED_CONNECTIONS
        ),
        "postgres_shared_buffers_mb": shared_buffers_mb,
        "postgres_shared_buffers": f"{shared_buffers_mb}MB",
        "postgres_work_mem_mb": work_mem_mb,
        "postgres_work_mem": f"{work_mem_mb}MB",
        "postgres_maintenance_work_mem_mb": maintenance_work_mem_mb,
        "postgres_maintenance_work_mem": f"{maintenance_work_mem_mb}MB",
        "postgres_delay": _POSTGRES_DELAY,
        "postgres_max_locks_per_transaction": _POSTGRES_MAX_LOCKS_PER_TRANSACTION,
    }

    if containers is not None:
        cpus_num = max(_round_half_up(avail_cpus / containers, 2), 0.5)
        mem_reservation_num = _round_half_up(avail_mem / containers * 0.7, 1)
        mem_limit_num = _round_half_up(avail_mem / containers * 1.0, 1)
        values.update(
            {
                "active_docker_container_count": containers,
                "cpus_num": cpus_num,
                "cpus": cpus_num,
                "mem_reservation_num": mem_reservation_num,
                "mem_reservation": f"{mem_reservation_num}g",
                "mem_limit_num": mem_limit_num,
                "mem_limit": f"{mem_limit_num}g",
            }
        )

    _VALUES_CACHE[cache_key] = values
    return values


class LookupModule(LookupBase):
    """
    Resolve one host-resource value, measured and computed in one place.

    Usage:
      lookup('resource', 'host_cpus')
      lookup('resource', 'mem_limit')
      query('resource', ['cpus', 'mem_limit'])

    The two measured inputs resolve in a fixed order: an inventory override
    (`RESOURCE_HOST_CPUS_OVERRIDE` / `RESOURCE_HOST_MEM_MB_OVERRIDE`), then the
    host's own hardware facts, then a probe of the machine this plugin runs on.
    The probe only applies to a target reached over the local connection,
    because a lookup executes on the Ansible controller: probing for a remote
    host would report the controller's hardware. That case raises and names the
    override to set.

    No value is ever substituted. Ansible's Linux hardware collector reads
    `/sys/block/<dev>/size` without a None guard and takes every hardware fact
    with it when that read fails, which is why the facts are a preferred source
    here rather than the only one.

    Optional kwarg:
      roles_dir — roles directory for the postgres connection split
                  (default: <cwd>/roles, matching the service lookup).
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if not terms:
            return []

        if len(terms) == 1 and isinstance(terms[0], (list, tuple)):
            terms = list(terms[0])

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        roles_dir = Path(kwargs.get("roles_dir") or Path.cwd() / "roles")

        keys = [str(term).strip() for term in terms]
        containers = _container_count(vars_) if _SHARE_KEYS.intersection(keys) else None
        values = _build(vars_, roles_dir, containers)

        results: list[Any] = []
        for key in keys:
            if key not in values:
                known = sorted(set(values) | _SHARE_KEYS)
                raise AnsibleError(
                    f"resource: unknown key '{key}'. Valid keys: {', '.join(known)}."
                )
            results.append(values[key])
        return results
