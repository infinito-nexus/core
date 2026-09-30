"""A role killed by the suite budget is reported, and not retried.

The retry exists for a Tor circuit flake. A run that hit the global timeout
fails the same way every time, so retrying it burns a second full budget: in
run 36651124458 that was 80% of some jobs' wall clock.

Excluding one is only safe while it still reaches the final fail task. The
stash resets ``_playwright_failures`` and only a retried role re-adds itself,
so an exclusion that emptied that list would turn a red job green. This test
renders the task's own expressions rather than matching their text, because the
failure it guards against is a wrong set operation, not wrong wording.
"""

from __future__ import annotations

import unittest
from typing import Any

import ast

import jinja2
from ansible.plugins.filter.mathstuff import FilterModule

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_str

from . import PROJECT_ROOT

ORCHESTRATE = (
    PROJECT_ROOT
    / "roles"
    / "test-e2e-playwright"
    / "tasks"
    / "01_setup"
    / "orchestrate.yml"
)
STASH = "Stash first-pass failures"


def stash_facts(failures: list[str], budget_timeouts: list[str]) -> dict[str, Any]:
    """Return the facts the stash task sets for the given first pass.

    Args:
        failures: every role the first pass recorded as failed.
        budget_timeouts: those of them killed by the suite budget.
    """
    env = jinja2.Environment(autoescape=False)  # noqa: S701 - renders a task's own list expression, not markup
    env.filters.update(FilterModule().filters())

    tasks = load_yaml_str(read_text(str(ORCHESTRATE)))
    task = next(t for t in tasks if STASH in t.get("name", ""))

    def resolve(expression: Any, context: dict[str, Any]) -> Any:
        if not isinstance(expression, str):
            return expression
        return ast.literal_eval(env.from_string(expression).render(**context))

    context: dict[str, Any] = {
        "_playwright_failures": failures,
        "_playwright_budget_timeouts": budget_timeouts,
    }
    for key, expression in (task.get("vars") or {}).items():
        context[key] = resolve(expression, context)

    return {
        key: resolve(expression, context)
        for key, expression in task["ansible.builtin.set_fact"].items()
    }


class TestBudgetTimeoutNotRetried(unittest.TestCase):
    def test_a_budget_timeout_is_kept_but_not_retried(self) -> None:
        facts = stash_facts(["web-app-docs", "web-app-foo"], ["web-app-docs"])

        self.assertEqual(facts["_playwright_retry_roles"], ["web-app-foo"])
        self.assertEqual(facts["_playwright_failures"], ["web-app-docs"])

    def test_an_ordinary_failure_is_retried_and_cleared(self) -> None:
        facts = stash_facts(["web-app-foo"], [])

        self.assertEqual(facts["_playwright_retry_roles"], ["web-app-foo"])
        self.assertEqual(facts["_playwright_failures"], [])

    def test_every_budget_timeout_still_reaches_the_fail_task(self) -> None:
        facts = stash_facts(["web-app-docs"], ["web-app-docs"])

        self.assertEqual(facts["_playwright_retry_roles"], [])
        self.assertEqual(facts["_playwright_failures"], ["web-app-docs"])


if __name__ == "__main__":
    unittest.main()
