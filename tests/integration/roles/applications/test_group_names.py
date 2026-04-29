import os
import sys
import re
import unittest

# ensure project root is on PYTHONPATH so we can import your CLI code
ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, os.pardir)
)
sys.path.insert(0, ROOT)

from cli.meta.applications.all import find_application_ids  # noqa: E402
from utils.cache.files import iter_project_files_with_content  # noqa: E402


class TestGroupApplications(unittest.TestCase):
    # regex to capture any literal check in group_names: 'name' in/not in group_names
    GROUP_CHECK_RE = re.compile(
        r"['\"](?P<name>[^'\"]+)['\"]\s*(?:in|not in)\s*group_names"
    )

    def test_group_name_checks_use_valid_application_ids(self):
        """
        Ensures that any string checked against group_names corresponds to a valid application ID.
        """
        valid_apps = find_application_ids()

        for filepath, text in iter_project_files_with_content(
            extensions=(".yml", ".yaml")
        ):
            # find all group_names checks in the file
            for match in self.GROUP_CHECK_RE.finditer(text):
                name = match.group("name")
                # the checked name must be one of the valid application IDs
                self.assertIn(
                    name,
                    valid_apps,
                    msg=(
                        f"{filepath}: group_names check uses '{name}', "
                        f"which is not a known application ID {valid_apps}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
