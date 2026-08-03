"""Consistency between the DR drill and the in-node unit trigger.

``trigger_units.sh`` runs inside a lab node, so it cannot read the paths SPOT
itself; the drill resolves it once and hands it over. Two relations are checked
across the pair: every call site passes the directory, and neither file carries
its own copy of the path.
"""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

TRIGGER = (
    PROJECT_ROOT
    / "scripts"
    / "tests"
    / "deploy"
    / "swarm"
    / "utils"
    / "trigger_units.sh"
)
DRILL = (
    PROJECT_ROOT
    / "scripts"
    / "tests"
    / "deploy"
    / "swarm"
    / "routine"
    / "backup"
    / "base.sh"
)
CALL = re.compile(r'bash "\$\{TRIGGER_UNITS\}"')
FULL_CALL = re.compile(
    r"""bash "\$\{TRIGGER_UNITS\}"\s+'[^']+'\s+"\$\{UNIT_DUMPS\}\"""",
)


class TestTriggerUnitsContract(unittest.TestCase):
    def setUp(self) -> None:
        self.trigger = read_text(str(TRIGGER))
        self.drill = read_text(str(DRILL))

    def test_every_call_site_supplies_both(self) -> None:
        self.assertEqual(
            len(CALL.findall(self.drill)), len(FULL_CALL.findall(self.drill))
        )

    def test_the_drill_has_at_least_one_call_site(self) -> None:
        self.assertGreater(len(CALL.findall(self.drill)), 0)

    def test_the_rescue_path_is_not_copied_into_the_script(self) -> None:
        self.assertNotIn("/tmp/infinito-rescue-diagnostics", self.trigger)
        self.assertNotIn("/tmp/infinito-rescue-diagnostics", self.drill)


if __name__ == "__main__":
    unittest.main()
