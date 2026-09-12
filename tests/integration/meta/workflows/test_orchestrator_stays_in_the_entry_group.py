from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

WORKFLOWS = PROJECT_ROOT / ".github/workflows"
ORCHESTRATOR = WORKFLOWS / "call-orchestrator.yml"
_CALLS_ORCHESTRATOR = re.compile(
    r"uses:\s*\./\.github/workflows/call-orchestrator\.yml"
)
_CALLED = re.compile(r"uses:\s*\./\.github/workflows/(call-[\w-]+\.yml)")
DEDUPLICATING_BUILDS = ("call-images-build-ci.yml", "call-images-mirror-missing.yml")


def _entries() -> list:
    return [
        path
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if _CALLS_ORCHESTRATOR.search(read_text(str(path)))
    ]


class TestOrchestratorStaysInTheEntryGroup(unittest.TestCase):
    def test_the_orchestrator_declares_no_concurrency_of_its_own(self) -> None:
        self.assertNotIn(
            "concurrency",
            load_yaml_any(str(ORCHESTRATOR)),
            "a called workflow's own group takes its jobs out of the entry's "
            "group, and the entry's cancel-in-progress then no longer reaches "
            "them: run 34614940508 kept 20 runners for seven hours after its "
            "successor arrived, because only chunk jobs were still alive",
        )

    def test_the_chain_below_it_declares_no_group_it_does_not_need(self) -> None:
        called = sorted(set(_CALLED.findall(read_text(str(ORCHESTRATOR)))))
        self.assertTrue(called)
        for name in called:
            if name in DEDUPLICATING_BUILDS:
                continue
            with self.subTest(called=name):
                self.assertNotIn(
                    "concurrency",
                    load_yaml_any(str(WORKFLOWS / name)),
                    f"{name} runs inside an orchestrator run, so its own group "
                    "takes those jobs out of the entry's; a superseded run "
                    "whose last live job is one of them keeps its runners. "
                    f"Only {' and '.join(DEDUPLICATING_BUILDS)} may carry one, "
                    "because their group deduplicates image builds across runs "
                    "rather than scoping a single run",
                )

    def test_every_entry_that_calls_it_carries_a_cancelling_group(self) -> None:
        entries = _entries()
        self.assertTrue(entries)
        for path in entries:
            with self.subTest(entry=path.name):
                concurrency = load_yaml_any(str(path)).get("concurrency") or {}
                self.assertTrue(
                    concurrency.get("group"),
                    f"{path.name} calls the orchestrator, so it owns the "
                    "grouping the orchestrator no longer declares",
                )
                self.assertIn(
                    "cancel-in-progress",
                    concurrency,
                    f"{path.name} must say whether a newer run supersedes a "
                    "running one; without it the deploy chunks run twice",
                )


if __name__ == "__main__":
    unittest.main()
