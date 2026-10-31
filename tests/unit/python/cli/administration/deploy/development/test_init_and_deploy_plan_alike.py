"""``init`` and ``deploy`` must hand the planner the same variant pins.

``init`` writes the inventory and ``deploy`` reads it back. The directory name
carries a round suffix only when the plan has more than one round, so a pin
that one of them applies and the other does not renames the directory under
the other's feet: init built ``<dir>-0`` while deploy looked for ``<dir>`` and
every app came back "not present in inventory".
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

PLANNER = "plan_dev_inventory_matrix"
PIN = "pinned_variants"

CALLERS = (
    "cli/administration/deploy/development/init.py",
    "cli/administration/deploy/development/deploy/cli.py",
)


def pins_at(source: str) -> list[bool]:
    """Whether each planner call in *source* passes the pins.

    Args:
        source: the module's text.
    """
    tree = ast.parse(source)
    found: list[bool] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else None
        if name != PLANNER:
            continue
        found.append(any(kw.arg == PIN for kw in node.keywords))
    return found


class TestInitAndDeployPlanAlike(unittest.TestCase):
    def test_both_entry_points_pass_the_variant_pins(self) -> None:
        missing: list[str] = []
        for rel in CALLERS:
            path = Path(PROJECT_ROOT) / rel
            calls = pins_at(read_text(str(path)))
            self.assertTrue(calls, f"{rel}: no {PLANNER} call found")
            missing.extend(rel for passes in calls if not passes)

        self.assertEqual(
            missing,
            [],
            f"These call {PLANNER} without {PIN}, so they plan a different "
            "number of rounds than their counterpart and disagree on the "
            f"inventory directory: {missing}",
        )


if __name__ == "__main__":
    unittest.main()
