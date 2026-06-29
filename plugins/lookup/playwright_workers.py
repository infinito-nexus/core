from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from ansible.plugins.lookup import LookupBase

# Conservative sizing for browser e2e that runs against the live, co-resident
# application stack. The binding constraint is rarely raw CPU: it is the
# application-under-test concurrency (Keycloak/Synapse rate limits, DB
# connections), RAM per Chromium worker, and the deployed stack sharing the
# host. So divide CPUs aggressively, reserve RAM for the stack, and hard-cap.
_PER_WORKER_GB = 1.5  # Chromium + node + headroom per worker
_RAM_FRACTION = 0.5  # leave half of RAM for the deployed stack under test
_CPU_DIVISOR = 4  # browser workers are heavy and the stack is co-resident
_HARD_CAP = 6  # app-under-test concurrency ceiling (login/rate limits)
_CI_CAP = 2  # CI runners: stay minimal and stable
_CI_ENV = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "JENKINS_URL")


def _cpu_count() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _ram_gb() -> float:
    try:
        with Path("/proc/meminfo").open(encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024.0 * 1024.0)
    except (OSError, ValueError, IndexError):
        pass  # best-effort: fall back to default when /proc/meminfo is unreadable/malformed
    return 4.0  # conservative fallback when /proc/meminfo is unreadable


def _is_ci() -> bool:
    return any(os.environ.get(k) for k in _CI_ENV)


def compute_workers(
    cpus: int,
    ram_gb: float,
    ci: bool,
    *,
    per_worker_gb: float = _PER_WORKER_GB,
    ram_fraction: float = _RAM_FRACTION,
    cpu_divisor: int = _CPU_DIVISOR,
    hard_cap: int = _HARD_CAP,
    ci_cap: int = _CI_CAP,
) -> int:
    cpu_workers = max(1, cpus // max(1, cpu_divisor))
    ram_workers = max(1, int((ram_gb * ram_fraction) // per_worker_gb))
    workers = min(cpu_workers, ram_workers, hard_cap)
    if ci:
        workers = min(workers, ci_cap)
    return max(1, workers)


class LookupModule(LookupBase):
    """
    lookup('playwright_workers')

    Conservative, stable parallel-worker count for the Playwright e2e suite.
    Derived from the control host's effective CPU and RAM, divided down because
    browser workers are heavy and run against the co-resident application stack,
    reserved against RAM, hard-capped for the application-under-test's
    concurrency limits, and reduced further on CI. Always returns an int >= 1.

    Tunable via kwargs: cpu_divisor, hard_cap, ci_cap, per_worker_gb,
    ram_fraction.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        return [
            compute_workers(
                _cpu_count(),
                _ram_gb(),
                _is_ci(),
                per_worker_gb=float(kwargs.get("per_worker_gb", _PER_WORKER_GB)),
                ram_fraction=float(kwargs.get("ram_fraction", _RAM_FRACTION)),
                cpu_divisor=int(kwargs.get("cpu_divisor", _CPU_DIVISOR)),
                hard_cap=int(kwargs.get("hard_cap", _HARD_CAP)),
                ci_cap=int(kwargs.get("ci_cap", _CI_CAP)),
            )
        ]
