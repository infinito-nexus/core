"""The orchestrator's two deploy layouts must stay mutually exclusive.

Each line renders swarm plus either the parallel single-node job or the
serial compose -> host chain; a `needs:` edge cannot be conditional, so both
layouts exist as jobs and the sequencing decision skips one. Nothing at
runtime proves the ten hand-written `if` expressions still agree with each
other, and the failure is silent in both directions: two layouts deploying
the same roles twice, or neither deploying anything.

These are structural assertions, not an expression evaluator. They catch the
mistakes this shape actually invites -- a copied sentinel, a missing chain
edge, a fail-fast guard pointing at the wrong predecessor.
"""

from __future__ import annotations

import unittest
from itertools import pairwise

from tests.utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml

ORCHESTRATOR = PROJECT_ROOT / ".github" / "workflows" / "ci-orchestrator.yml"

LINES = {"priority": "-priority", "regular": ""}
CHAIN = ("test-deploy-swarm", "test-deploy-compose", "test-deploy-host")
PARALLEL = "test-deploy-single-node"


def _jobs() -> dict:
    return load_yaml(str(ORCHESTRATOR))["jobs"]


def _job(name: str, suffix: str) -> dict:
    return _jobs()[f"{name}{suffix}"]


def _condition(name: str, suffix: str) -> str:
    return " ".join(str(_job(name, suffix).get("if", "")).split())


def _needs(name: str, suffix: str) -> list[str]:
    declared = _job(name, suffix).get("needs", [])
    return [declared] if isinstance(declared, str) else list(declared)


class TestLayoutsAreMutuallyExclusive(unittest.TestCase):
    def test_the_serial_chain_selects_on_the_serial_sentinel(self) -> None:
        for line, suffix in LINES.items():
            for name in CHAIN[1:]:
                with self.subTest(line=line, job=name):
                    self.assertIn(
                        f"needs.sequencing.outputs.{line} == 'serial'",
                        _condition(name, suffix),
                    )

    def test_the_parallel_job_selects_on_the_parallel_sentinel(self) -> None:
        for line, suffix in LINES.items():
            with self.subTest(line=line):
                self.assertIn(
                    f"needs.sequencing.outputs.{line} == 'parallel'",
                    _condition(PARALLEL, suffix),
                )

    def test_a_skipped_dependency_cannot_skip_a_serial_job(self) -> None:
        for line, suffix in LINES.items():
            for name in CHAIN[1:]:
                with self.subTest(line=line, job=name):
                    self.assertIn("always()", _condition(name, suffix))


class TestSerialChain(unittest.TestCase):
    def test_each_mode_waits_for_its_predecessor(self) -> None:
        for line, suffix in LINES.items():
            for predecessor, successor in pairwise(CHAIN):
                with self.subTest(line=line, job=successor):
                    self.assertIn(f"{predecessor}{suffix}", _needs(successor, suffix))

    def test_swarm_leads_and_waits_for_no_decision(self) -> None:
        """It runs first in either layout, so making it wait for the
        sequencing job would delay every run for nothing."""
        for line, suffix in LINES.items():
            with self.subTest(line=line):
                self.assertNotIn("sequencing", _needs(CHAIN[0], suffix))

    def test_fail_fast_guards_the_immediate_predecessor(self) -> None:
        for line, suffix in LINES.items():
            for predecessor, successor in pairwise(CHAIN):
                with self.subTest(line=line, job=successor):
                    condition = _condition(successor, suffix)
                    self.assertIn("inputs.mode_fail_fast", condition)
                    self.assertIn(f"needs.{predecessor}{suffix}.result", condition)


class TestRegularLineWaitsForPriority(unittest.TestCase):
    def test_every_priority_job_gates_every_regular_job(self) -> None:
        priority = [f"{name}-priority" for name in (PARALLEL, *CHAIN)]
        for name in (PARALLEL, *CHAIN):
            with self.subTest(job=name):
                self.assertLessEqual(set(priority), set(_needs(name, "")))


if __name__ == "__main__":
    unittest.main()
