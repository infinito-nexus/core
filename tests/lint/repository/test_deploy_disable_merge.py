from __future__ import annotations

import re
import unittest

from cli.administration.inventory.provision.services_disabler import (
    parse_services_disabled,
)
from tests.utils import PROJECT_ROOT
from utils.cache.files import read_text

DEPLOY_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "call-test-deploy.yml"

_DISABLE_ENV = re.compile(r"^\s+disable:\s*\$\{\{\s*(.*?)\s*\}\}\s*$")
_FORMAT = re.compile(
    r"format\('(?P<template>[^']*)',\s*matrix\.disable,\s*inputs\.disable\)"
)
_FALLBACK = re.compile(r"matrix\.disable\s*\|\|\s*inputs\.disable")

OLD_EXPRESSION = "matrix.disable || inputs.disable"


def disable_expressions() -> list[str]:
    return [
        match.group(1)
        for line in read_text(str(DEPLOY_WORKFLOW)).splitlines()
        if not line.lstrip().startswith("#")
        for match in [_DISABLE_ENV.match(line)]
        if match
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


if __name__ == "__main__":
    unittest.main()
