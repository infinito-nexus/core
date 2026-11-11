from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr, redirect_stdout

from cli.meta.stacks.__main__ import main
from utils.stacks import (
    CLASSES,
    Stack,
    calls,
    load,
    makefile_calls,
    problems,
    resolve,
)

CLASS_TABLE = {
    "cache": "always-on",
    "tools": "on-demand",
    "test-runner": "long-lived",
    "deploy": "on-demand",
}
TEST_RUNNER = ["cache", "test-runner"]
RESOLVED = {
    "test": TEST_RUNNER,
    "lint": TEST_RUNNER,
    "quality-high": TEST_RUNNER,
    "test-unit": TEST_RUNNER,
    "compose-deploy": ["cache", "deploy"],
    "compose-exec": ["cache", "deploy"],
    "i18n-translate": ["cache", "tools"],
    "i18n-tune": ["cache", "tools"],
    "test-oracle": ["cache", "test-runner", "tools"],
    "cache-evict": ["cache"],
    "dotenv": [],
}
FIXTURE = (
    ".PHONY: all\n"
    "all: first\n"
    '\t@"$(MAKE)" second\n'
    "\t@bash scripts/make/parallel.sh third \\\n"
    "\t\tfourth\n"
    "first:\n"
    "\t@true\n"
    "second:\n"
    "third:\n"
    "fourth:\n"
    "VARIABLE := all\n"
    "unrelated:\n"
    "\t@echo all\n"
)


class TestDeclaration(unittest.TestCase):
    def setUp(self) -> None:
        self.stacks = load()
        self.graph = makefile_calls()

    def test_every_stack_carries_its_lifecycle_class(self) -> None:
        self.assertEqual(
            {name: stack.lifecycle for name, stack in self.stacks.items()},
            CLASS_TABLE,
        )
        self.assertTrue(all(s.lifecycle in CLASSES for s in self.stacks.values()))

    def test_the_declaration_names_only_makefile_targets_and_known_stacks(
        self,
    ) -> None:
        self.assertEqual(problems(self.stacks, set(self.graph)), [])

    def test_every_stack_names_the_targets_that_need_it(self) -> None:
        for stack in self.stacks.values():
            with self.subTest(stack=stack.name):
                self.assertTrue(stack.targets)

    def test_every_wrapped_test_and_lint_target_needs_the_test_runner(
        self,
    ) -> None:
        wrapped = {
            target
            for target in self.graph
            if target.startswith(("test-unit-", "lint-"))
            or target in ("test-external", "test-integration", "test-lint")
        }
        self.assertLessEqual(wrapped, set(self.stacks["test-runner"].targets))


class TestProblems(unittest.TestCase):
    def test_an_unknown_class_need_and_target_are_named(self) -> None:
        broken = {
            "a": Stack("a", "sometimes", ("ghost", "a"), ("no-such-target",)),
        }
        found = problems(broken, {"real"})
        self.assertEqual(len(found), 4)
        self.assertIn("class 'sometimes'", found[0])
        self.assertIn("needs ghost", found[1])
        self.assertIn("needs itself", found[2])
        self.assertIn("no-such-target", found[3])


class TestCalls(unittest.TestCase):
    def test_prerequisites_make_calls_and_parallel_fan_out_are_followed(
        self,
    ) -> None:
        graph = calls(FIXTURE)
        self.assertEqual(graph["all"], {"first", "second", "third", "fourth"})
        self.assertEqual(graph["unrelated"], set())
        self.assertNotIn("VARIABLE", graph)


class TestResolve(unittest.TestCase):
    def setUp(self) -> None:
        self.stacks = load()
        self.graph = makefile_calls()

    def test_the_pinned_targets_start_exactly_their_stacks(self) -> None:
        for target, expected in RESOLVED.items():
            with self.subTest(target=target):
                self.assertEqual(resolve(target, self.stacks, self.graph), expected)

    def test_a_needed_stack_comes_first(self) -> None:
        stacks = {
            "late": Stack("late", "on-demand", ("early",), ("go",)),
            "early": Stack("early", "always-on", (), ()),
        }
        self.assertEqual(resolve("go", stacks, {"go": set()}), ["early", "late"])

    def test_an_unknown_target_is_refused(self) -> None:
        with self.assertRaises(KeyError):
            resolve("no-such-target", self.stacks, self.graph)


class TestCli(unittest.TestCase):
    def _run(self, *argv: str) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_the_dry_run_prints_the_stacks_with_their_class(self) -> None:
        code, out, _ = self._run("compose-deploy")
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            {
                "target": "compose-deploy",
                "stacks": [
                    {"name": "cache", "class": "always-on"},
                    {"name": "deploy", "class": "on-demand"},
                ],
            },
        )

    def test_an_unknown_target_exits_non_zero(self) -> None:
        code, out, err = self._run("no-such-target")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("no-such-target", err)


if __name__ == "__main__":
    unittest.main()
