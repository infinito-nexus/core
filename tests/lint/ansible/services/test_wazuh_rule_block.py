"""Lint: every Wazuh opt-in owns a valid rule block and stays inside it.

A role opts in through ``services.wazuh`` in its ``meta/services.yml`` and
declares ``services.wazuh.rule_block``, the first ID of its 100-ID block.
The block start is the central parent rule; the role's own rules use the
rest of the block and chain to it. See
:func:`utils.roles.applications.services.wazuh.rule_block_errors`.
"""

from __future__ import annotations

import unittest

from utils.cache import ROLES_DIR
from utils.cache.applications import get_application_defaults
from utils.roles.applications.services.wazuh import rule_block_errors


class TestWazuhRuleBlock(unittest.TestCase):
    def test_rule_blocks_are_valid(self):
        errors = rule_block_errors(
            get_application_defaults(roles_dir=ROLES_DIR), ROLES_DIR
        )
        if errors:
            self.fail("Wazuh rule block violations:\n" + "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
