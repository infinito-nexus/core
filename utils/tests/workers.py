"""How many pytest-xdist workers one test suite gets.

The budget is ``target x cpus``: ``cpus`` the CPUs this process may run on,
``target`` the workers per CPU of the environment (``INFINITO_TEST_CPU_TARGET_CI``
on a GitHub-hosted runner, ``INFINITO_TEST_CPU_TARGET_LOCAL`` elsewhere). The
pytest suites ``scripts/make/parallel.sh`` runs side by side split it by the
time each spent in its last JUnit report, or by ``FALLBACK_WEIGHTS`` while one
of them has none; a suite running alone takes all of it.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from utils.tests.pytest.longest_first import scope_durations

FALLBACK_WEIGHTS = {"integration": 0.45, "unit": 0.3, "lint": 0.2, "external": 0.05}
SUITE_OF_TARGET = {
    "test-external": "external",
    "test-integration": "integration",
    "test-lint": "lint",
    "test-unit": "unit",
    "test-unit-python": "unit",
}
REPORTS = Path("build/test-reports")


def weights(suites: set[str], reports: Path) -> dict[str, float]:
    """
    Args:
        suites: the pytest suites running side by side.
        reports: the directory holding ``<suite>.xml`` of the last run.

    Returns:
        Each suite's summed case time, or ``FALLBACK_WEIGHTS`` for all of them
        when one has no recorded time.
    """
    recorded = {
        suite: sum(scope_durations(reports / f"{suite}.xml").values())
        for suite in suites
    }
    if all(recorded.values()):
        return recorded
    return {suite: FALLBACK_WEIGHTS[suite] for suite in suites}


def workers(
    suite: str, siblings: list[str], cpus: int, target: float, reports: Path
) -> int:
    """
    Args:
        suite: this run's ``INFINITO_TEST_TYPE``.
        siblings: every make target the enclosing parallel dispatches started.
        cpus: the CPUs this process may run on.
        target: workers per CPU summed over the suites running side by side.
        reports: the directory holding ``<suite>.xml`` of the last run.

    Returns:
        The xdist worker count, at least one.
    """
    budget = cpus * target
    peers = {SUITE_OF_TARGET[name] for name in siblings if name in SUITE_OF_TARGET}
    if suite not in peers:
        return max(1, round(budget))
    shares = weights(peers, reports)
    return max(1, round(budget * shares[suite] / sum(shares.values())))


def main() -> None:
    on_ci = os.environ.get("INFINITO_RUNNING_ON_GITHUB") == "true"
    target = os.environ[
        "INFINITO_TEST_CPU_TARGET_CI" if on_ci else "INFINITO_TEST_CPU_TARGET_LOCAL"
    ]
    print(
        workers(
            sys.argv[1],
            os.environ.get("PARALLEL_SIBLINGS", "").split(),
            len(os.sched_getaffinity(0)),
            float(target),
            REPORTS,
        )
    )


if __name__ == "__main__":
    main()
