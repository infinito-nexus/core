"""The MCP reconciliation runs after the app pass and before anything reads it.

Providers write their credentials during the app pass, and the end-to-end tests
read the converged state. The reconciliation therefore has exactly one valid
window, and both edges are silent when crossed: moved earlier it converges
against providers that have not deployed, moved into the destructor it runs
after the tests that need it - and `any_errors_fatal` means one red test skips
it entirely.

Neither mistake fails anything, which is why this is pinned here rather than
left to review.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: mcp-reconcile-placement`` on, or directly above, the include.
"""

from __future__ import annotations

import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text

from . import PROJECT_ROOT

_RULE = "mcp-reconcile-placement"
_ROLE = "sys-svc-mcp-reconcile"
_STAGE = PROJECT_ROOT / "tasks" / "stages" / "02_server.yml"
_DESTRUCTOR = PROJECT_ROOT / "tasks" / "stages" / "03_destructor.yml"
_APP_PASS = "tasks/groups/"
_READER = "test-e2e-playwright"


def _line_of(lines: list[str], needle: str) -> int | None:
    return next((i for i, raw in enumerate(lines, 1) if needle in raw), None)


class TestMcpReconcilePlacement(unittest.TestCase):
    def setUp(self) -> None:
        self.lines = read_text(str(_STAGE)).splitlines()

    def test_the_reconciliation_sits_between_the_app_pass_and_its_reader(self) -> None:
        reconcile = _line_of(self.lines, _ROLE)
        self.assertIsNotNone(
            reconcile, f"{_ROLE} is not invoked from {_STAGE.name}; nothing converges"
        )
        if is_suppressed_at(self.lines, reconcile, _RULE):
            return
        app_pass = _line_of(self.lines, _APP_PASS)
        reader = _line_of(self.lines, _READER)
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
