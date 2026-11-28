from __future__ import annotations

import os
import re
import subprocess
import unittest

from cli.administration.inventory.provision.services.disabler import (
    parse_services_disabled,
)
from tests.utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

DEPLOY_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"

_EXPRESSION = re.compile(r"\$\{\{\s*(?P<body>.*?)\s*\}\}")
_FORMAT = re.compile(
    r"format\('(?P<template>[^']*)',\s*matrix\.disable,\s*inputs\.disable\)"
)
_FALLBACK = re.compile(r"matrix\.disable\s*\|\|\s*inputs\.disable")

OLD_EXPRESSION = "matrix.disable || inputs.disable"


def disable_expressions() -> list[str]:
    """Returns:
    The ``disable`` value of every step env, without its ``${{ }}`` wrapper.
    """
    values = [
        str(step["env"]["disable"]).strip()
        for job in load_yaml_any(str(DEPLOY_WORKFLOW))["jobs"].values()
        for step in job.get("steps") or []
        if isinstance(step.get("env"), dict) and "disable" in step["env"]
    ]
    return [
        match["body"] if (match := _EXPRESSION.fullmatch(value)) else value
        for value in values
    ]


def evaluate(expression: str, row: str, passed: str) -> list[str]:
    """The provider keys a step receives, as the deploy parses them.

    Args:
        expression: the step-env expression, without the ``${{ }}`` wrapper.
        row: the matrix row's ``disable`` value.
        passed: the caller's ``disable`` input.
    """
    template = _FORMAT.fullmatch(expression)
    if template:
        return parse_services_disabled(template.group("template").format(row, passed))
    if _FALLBACK.fullmatch(expression):
        return parse_services_disabled(row or passed)
    raise AssertionError(f"unsupported disable expression: {expression}")


class TestDeployDisableMerge(unittest.TestCase):
    def test_both_deploy_steps_set_disable(self) -> None:
        self.assertEqual(len(disable_expressions()), 2)

    def test_row_tokens_keep_the_passed_list(self) -> None:
        for expression in disable_expressions():
            with self.subTest(expression=expression):
                self.assertEqual(
                    evaluate(expression, "tor", "docs,matomo"),
                    ["tor", "docs", "matomo"],
                )

    def test_passed_list_reaches_a_row_without_tokens(self) -> None:
        for expression in disable_expressions():
            with self.subTest(expression=expression):
                self.assertEqual(evaluate(expression, "", "docs"), ["docs"])

    def test_row_tokens_reach_a_caller_without_a_list(self) -> None:
        for expression in disable_expressions():
            with self.subTest(expression=expression):
                self.assertEqual(evaluate(expression, "tor", ""), ["tor"])

    def test_the_old_fallback_drops_the_passed_list(self) -> None:
        self.assertEqual(evaluate(OLD_EXPRESSION, "tor", "docs,matomo"), ["tor"])

    def test_discovery_warns_when_a_passed_list_can_orphan_a_covered_row(self) -> None:  # nocheck: test.text-presence -- selects the warn step from the parsed workflow, the next test runs it  # fmt: skip
        self.assertTrue(
            warning_steps(),
            "the covered-row cut ignores the passed disable, so discovery must "
            "warn whenever one is passed",
        )

    def test_the_passed_list_cannot_inject_a_workflow_command(self) -> None:
        for step in warning_steps():
            with self.subTest(step=step["name"]):
                printed = subprocess.run(
                    ["bash", "-c", step["run"]],
                    env={
                        **os.environ,
                        "PASSED_DISABLE": "docs\n::error::forged%0A::add-mask::x\r",
                    },
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout
                self.assertEqual(printed.count("\n"), 1, printed)
                self.assertEqual(printed.count("::"), 2, printed)
                self.assertNotIn("%", printed)
                self.assertIn("disable=docserrorforged0Aadd-maskx ", printed)


def warning_steps() -> list[dict]:
    """The discover steps that warn about a passed ``disable``."""
    steps = load_yaml_any(str(DEPLOY_WORKFLOW))["jobs"]["discover"]["steps"]
    return [
        step
        for step in steps
        if "inputs.disable" in str(step.get("if", ""))
        and "::warning" in str(step.get("run", ""))
    ]


if __name__ == "__main__":
    unittest.main()
