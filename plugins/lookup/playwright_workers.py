from __future__ import annotations

import contextlib
import os
from typing import Any

from ansible.plugins.lookup import LookupBase
from ansible.template import trust_as_template

from utils.env.runtime import mem_available_mb, mem_total_mb

_PER_WORKER_GB = 1.5
_RAM_FRACTION = 0.5
_CPU_DIVISOR = 4
_HARD_CAP = 6
_CI_CAP = 2
_ONION_FACTOR = 2
_ONION_CAP = 3
_CI_ENV = ("CI", "GITHUB_ACTIONS", "GITLAB_CI", "BUILDKITE", "JENKINS_URL")


def _cpu_count() -> int:
    try:
        return max(1, len(os.sched_getaffinity(0)))
    except (AttributeError, OSError):
        return max(1, os.cpu_count() or 1)


def _ram_gb() -> float:
    """Memory a new worker may actually claim, in GB.

    MemAvailable, not MemTotal: the ceiling exists to stop the sidecar from
    competing with what already runs, and on a CI runner the deployed stacks
    hold most of the machine by the time the suite starts. Sizing from the
    total made the term inert -- it computed five workers on a 16 GB runner
    that had 5.5 GB free -- so the CI cap was the only thing ever binding.
    Falls back to the total, then to a floor, when /proc does not answer.
    """
    available_mb = mem_available_mb()
    if available_mb:
        return available_mb / 1024
    total_mb = mem_total_mb()
    return total_mb / 1024 if total_mb else 4.0


def _is_ci() -> bool:
    return any(os.environ.get(k) for k in _CI_ENV)


def compute_workers(
    cpus: int,
    ram_gb: float,
    ci: bool,
    *,
    onion: bool = False,
    per_worker_gb: float = _PER_WORKER_GB,
    ram_fraction: float = _RAM_FRACTION,
    cpu_divisor: int = _CPU_DIVISOR,
    hard_cap: int = _HARD_CAP,
    ci_cap: int = _CI_CAP,
    onion_factor: int = _ONION_FACTOR,
    onion_cap: int = _ONION_CAP,
) -> int:
    """Workers the host can carry, and the transport can use.

    Args:
        cpus: usable cores.
        ram_gb: memory a worker may claim, taken from what is free rather than
            from what the machine has.
        ci: whether a CI runner is executing, which lowers the ceiling.
        onion: whether the suite reaches its target over Tor. A run against a
            `.onion` address waits on circuits rather than on the CPU: measured
            on one Nextcloud variant at equal mode and filesystem, the sidecar
            took 4817s over Tor against 911s on clearnet, and Tor burns no
            browser CPU. The CPU divisor cannot describe that phase, so the
            count is raised instead of derived from cores. Raised by a factor
            rather than freed, because every worker holds its own circuits.
        onion_factor: multiplier applied to the CPU-derived count over Tor.
        onion_cap: ceiling for the Tor case, independent of the CI cap.

    Returns:
        Worker count, never below one.
    """
    cpu_workers = max(1, cpus // max(1, cpu_divisor))
    ram_workers = max(1, int((ram_gb * ram_fraction) // per_worker_gb))
    workers = min(cpu_workers, ram_workers, hard_cap)
    if ci:
        workers = min(workers, ci_cap)
    if onion:
        workers = min(workers * onion_factor, ram_workers, onion_cap)
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

    def _targets_onion(self, variables: dict[str, Any] | None) -> bool:
        """Whether the app under test is reached over a `.onion` address.

        Read from the play rather than from a parameter so a caller cannot
        forget it: the transport decides whether the phase is latency-bound,
        and the caller that asks for a worker count has no reason to know.
        """
        application_id = (variables or {}).get("application_id")
        templar = getattr(self, "_templar", None)
        if not application_id or templar is None:
            return False
        with contextlib.suppress(Exception):
            application_id = templar.template(application_id)
            base = templar.template(
                trust_as_template(
                    "{{ lookup('tls', " + repr(str(application_id)) + ", 'url.base') }}"
                )
            )
            return ".onion" in str(base)
        return False

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        return [
            compute_workers(
                _cpu_count(),
                _ram_gb(),
                _is_ci(),
                onion=bool(kwargs.get("onion", self._targets_onion(variables))),
                per_worker_gb=float(kwargs.get("per_worker_gb", _PER_WORKER_GB)),
                ram_fraction=float(kwargs.get("ram_fraction", _RAM_FRACTION)),
                cpu_divisor=int(kwargs.get("cpu_divisor", _CPU_DIVISOR)),
                hard_cap=int(kwargs.get("hard_cap", _HARD_CAP)),
                ci_cap=int(kwargs.get("ci_cap", _CI_CAP)),
                onion_factor=int(kwargs.get("onion_factor", _ONION_FACTOR)),
                onion_cap=int(kwargs.get("onion_cap", _ONION_CAP)),
            )
        ]
