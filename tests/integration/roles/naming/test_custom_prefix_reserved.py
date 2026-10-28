"""The custom-role prefix is reserved for roles an inventory pulls.

``roles/web-app-cst-*`` is where the pull places the custom roles an
inventory declares, and Git ignores that path. A role committed to core
under that prefix would be replaced or deleted by the next pull, so no
tracked file may live there.
"""

from __future__ import annotations

import subprocess
import unittest

from utils.roles.custom import PREFIX, ROLES_GLOB

from . import PROJECT_ROOT


class TestCustomPrefixReserved(unittest.TestCase):
    def test_no_in_tree_role_uses_the_custom_prefix(self):
        tracked = subprocess.run(
            ["git", "-c", "safe.directory=*", "ls-files", "-z", "--", ROLES_GLOB],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        roles = sorted({path.split("/")[1] for path in tracked.split("\0") if path})
        self.assertEqual(
            [],
            roles,
            f"In-tree roles must not start with {PREFIX}, the prefix of the custom "
            f"roles an inventory pulls into roles/; rename: {', '.join(roles)}",
        )


if __name__ == "__main__":
    unittest.main()
