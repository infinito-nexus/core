from __future__ import annotations

import unittest

from utils.cache.files import read_text
from utils.stacks.declaration import declared_targets, load, unaddressed
from utils.stacks.makefile import MAKEFILE
from utils.stacks.reach import reaching
from utils.stacks.sites import starts
from utils.stacks.sources import source_graph
from utils.stacks.starts import start_problems

KNOWN_CALLERS = (
    "compose-down",
    "compose-up",
    "infra-up",
    "test-unit-python",
    "worktree-down",
)


class TestTargetsDeclareStacks(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        makefile = read_text(str(MAKEFILE))
        graph = source_graph()
        cls.reaching = reaching(makefile, graph)
        cls.starting = reaching(makefile, graph, starts(graph))
        cls.stacks = load()
        cls.free = unaddressed()
        cls.declared = declared_targets(cls.stacks, cls.free)
        cls.start_problems = start_problems(makefile, graph, cls.stacks, cls.free)

    def test_every_target_that_reaches_a_compose_helper_is_declared(self) -> None:
        missing = [
            f"{target}: {' -> '.join(chain)}"
            for target, chain in sorted(self.reaching.items())
            if target not in self.declared
        ]
        self.assertEqual(
            missing,
            [],
            "Name each target in compose/stacks.yml: under `targets` of the "
            "stacks it starts, `stops` of the stacks it stops, or `unaddressed`.",
        )

    def test_every_unaddressed_target_still_reaches_a_compose_helper(self) -> None:
        self.assertEqual(sorted(set(self.free) - set(self.reaching)), [])

    def test_every_starter_is_declared_under_the_stack_it_starts(self) -> None:
        self.assertEqual(
            self.start_problems,
            [],
            "A target that starts a stack belongs under `targets` of that stack, "
            "or of a stack whose `override` names it.",
        )

    def test_the_scan_finds_the_known_helper_callers(self) -> None:
        for target in KNOWN_CALLERS:
            with self.subTest(target=target):
                self.assertIn(target, self.reaching)
        self.assertIn("compose-up", self.starting)


if __name__ == "__main__":
    unittest.main()
