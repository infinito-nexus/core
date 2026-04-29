import os
import re
import sys
import unittest

# ensure project root is on PYTHONPATH so we can import the CLI code
ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, os.pardir, os.pardir)
)
sys.path.insert(0, ROOT)

from cli.meta.applications.all import find_application_ids  # noqa: E402
from utils.cache.files import iter_project_files_with_content  # noqa: E402


class TestValidApplicationUsage(unittest.TestCase):
    """
    Integration test to ensure that only valid application IDs
    are used in all .yml, .yaml, .yml.j2, .yaml.j2, and .py files.

    It detects:
    - lookup('applications', 'name')       (canonical applications lookup)
    - get_domain('name')                    (filter helper for domain resolution)

    Dynamic calls such as lookup('applications', application_id) are not
    validated here, because the app ID is a runtime variable.
    """

    # Literal app-id captured from lookup('applications', 'name') / lookup("applications", "name")
    LOOKUP_APPLICATIONS_RE = re.compile(
        r"lookup\(\s*['\"]applications['\"]\s*,\s*['\"](?P<name>[^'\"]+)['\"]"
    )
    APPLICATION_DOMAIN_RE = re.compile(
        r"get_domain\(\s*['\"](?P<name>[^'\"]+)['\"]\s*\)"
    )

    @staticmethod
    def _line_no_and_col(content: str, index: int) -> tuple[int, int]:
        """
        Return 1-based (line_no, col) for a 0-based absolute index into content.
        """
        line_no = content.count("\n", 0, index) + 1
        line_start = content.rfind("\n", 0, index) + 1
        col = (index - line_start) + 1
        return line_no, col

    def test_application_references_use_valid_ids(self):
        valid_apps = find_application_ids()

        patterns = (
            self.LOOKUP_APPLICATIONS_RE,
            self.APPLICATION_DOMAIN_RE,
        )

        for filepath, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml", ".yml.j2", ".yaml.j2", ".py"),
            exclude_tests=True,
        ):
            for pattern in patterns:
                for match in pattern.finditer(content):
                    start = match.start()

                    # Determine the full line containing this match
                    line_start = content.rfind("\n", 0, start) + 1
                    line_end = content.find("\n", start)
                    line = content[line_start : line_end if line_end != -1 else None]

                    # Skip any import or from-import lines
                    if line.strip().startswith(("import ", "from ")):
                        continue

                    name = match.group("name")

                    line_no, col = self._line_no_and_col(content, start)

                    # each found reference must be in valid_apps
                    self.assertIn(
                        name,
                        valid_apps,
                        msg=(
                            f"{filepath}: reference to application '{name}' is invalid.\n"
                            f"Location: line {line_no}, col {col}\n"
                            f"Line: {line.rstrip()}\n"
                            f"Known IDs: {sorted(valid_apps)}"
                        ),
                    )


if __name__ == "__main__":
    unittest.main()
