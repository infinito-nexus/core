"""Lint: every Wazuh opt-in has a journald tag of its own.

The tag and the compose project of an opted-in role are its entity name. It
must not be empty, must not be a tag the agent or the ruleset reserves, must
not contain the name Wazuh's default ``systemd`` decoder claims, and no other
role may share it. See
:func:`utils.roles.applications.services.wazuh.tag_errors`.
"""

from __future__ import annotations

import unittest

from utils.cache import ROLES_DIR
from utils.cache.applications import get_application_defaults
from utils.roles.applications.services.wazuh import tag_errors


class TestWazuhTags(unittest.TestCase):
    def test_opted_in_tags_are_usable_and_unique(self):
        errors = tag_errors(get_application_defaults(roles_dir=ROLES_DIR), ROLES_DIR)
        if errors:
            self.fail("Wazuh tag violations:\n" + "\n".join(errors))


if __name__ == "__main__":
    unittest.main()
