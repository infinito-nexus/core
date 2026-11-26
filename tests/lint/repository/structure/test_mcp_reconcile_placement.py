"""The MCP reconciliation runs after the app pass and before anything reads it.

Providers write their credentials during the app pass, and the end-to-end tests
read the converged state. The reconciliation therefore has exactly one valid
window, and both edges are silent when crossed: moved earlier it converges
against providers that have not deployed, moved into the destructor it runs
after the tests that need it - and `any_errors_fatal` means one red test skips
it entirely.

Neither mistake fails anything, which is why this is pinned here rather than
left to review.
"""

from __future__ import annotations

import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT, includes_role, includes_tasks, position, tasks_of

_ROLE = "sys-svc-mcp-reconcile"
_STAGE = PROJECT_ROOT / "tasks" / "stages" / "02_server.yml"
_DESTRUCTOR = PROJECT_ROOT / "tasks" / "stages" / "03_destructor.yml"
_APP_PASS = "tasks/utils/setup/group.yml"
_READER = "test-e2e-playwright"


class TestMcpReconcilePlacement(unittest.TestCase):
    def setUp(self) -> None:
        self.tasks = tasks_of(_STAGE)

    def test_the_reconciliation_sits_between_the_app_pass_and_its_reader(self) -> None:
        reconcile = position(self.tasks, includes_role(_ROLE))
        self.assertIsNotNone(
            reconcile, f"{_ROLE} is not invoked from {_STAGE.name}; nothing converges"
        )
        app_pass = position(self.tasks, includes_tasks(_APP_PASS))
        reader = position(self.tasks, includes_role(_READER))
        self.assertIsNotNone(app_pass, f"{_STAGE.name} no longer includes the app pass")
        self.assertIsNotNone(reader, f"{_STAGE.name} no longer runs {_READER}")
        self.assertLess(
            app_pass,
            reconcile,
            "reconciliation before the app pass converges against providers that "
            "have not written their credentials yet",
        )
        self.assertLess(
            reconcile,
            reader,
            f"{_READER} reads the converged state, so it must run after the "
            f"reconciliation, not before it",
        )

    def test_the_reconciliation_is_not_deferred_to_the_destructor(self) -> None:
        self.assertNotIn(
            _ROLE,
            read_text(str(_DESTRUCTOR)),
            "the destructor runs after the end-to-end tests, and any_errors_fatal "
            "skips it entirely once one of them is red",
        )


if __name__ == "__main__":
    unittest.main()
