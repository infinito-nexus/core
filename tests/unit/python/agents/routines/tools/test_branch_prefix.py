"""Unit test: the branch-prefix check accepts the allowed kinds and refuses the
rest by the first path segment, applies the same list as the local branch-name
lint, and the push routine refuses a wrong prefix before its push step."""

from __future__ import annotations

import unittest

from agents.routines import push_trigger_pull
from agents.routines.tools.branch_prefix import ALLOWED_PREFIXES, prefix_ok
from tests.lint.repository.naming.test_branch_name import BRANCH_RE, VALID_PREFIXES

ALLOWED = (
    "feature/agents",
    "fix/login-500/taiga-123",
    "update/pins",
    "chore/cleanup",
    "documentation/contributing-setup",
    "agent/improve-commit-instructions",
    "dependabot/pip/requests-2.32.0",
    "alert-autofix-261",
)
REFUSED = (
    "wip/experiment",
    "feature-no-slash",
    "feature",
    "feat/agents",
    "alert-autofix/ql-123",
)


class TestBranchPrefix(unittest.TestCase):
    def test_allowed_prefixes_pass(self) -> None:
        for branch in ALLOWED:
            self.assertTrue(prefix_ok(branch), branch)

    def test_unknown_prefix_refused(self) -> None:
        for branch in REFUSED:
            self.assertFalse(prefix_ok(branch), branch)

    def test_the_local_lint_applies_the_same_list(self) -> None:
        self.assertEqual(ALLOWED_PREFIXES, frozenset(VALID_PREFIXES))
        for branch in ALLOWED + REFUSED:
            self.assertEqual(prefix_ok(branch), bool(BRANCH_RE.match(branch)), branch)

    def test_the_routine_refuses_before_the_push(self) -> None:
        steps = {step.id: step for step in push_trigger_pull.STEPS}
        order = [step.id for step in push_trigger_pull.STEPS]
        self.assertLess(order.index("prefix"), order.index("push"))
        refused = steps["prefix"].fn({"branch": "wip/experiment"})["prefix"]
        allowed = steps["prefix"].fn({"branch": "feature/agents"})["prefix"]
        self.assertEqual(dict(steps["prefix"].branches)[refused], "refuse")
        self.assertEqual(dict(steps["prefix"].branches)[allowed], "predict")
        self.assertEqual(steps["refuse"].kind, "terminal")


if __name__ == "__main__":
    unittest.main()
