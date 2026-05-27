import os
import re
import unittest
from pathlib import Path


class TestNoApplicationsVariableUsage(unittest.TestCase):
    """
    This test ensures that the pattern `applications[some_variable]` is not used anywhere
    under the roles/ directory. Instead, the usage of utils.roles.applications.config.get should be preferred.
    """

    APPLICATIONS_VARIABLE_PATTERN = re.compile(
        r"applications\[\s*[a-zA-Z_][a-zA-Z0-9_]*\s*\]"
    )

    def test_no_applications_variable_usage(self):
        from . import PROJECT_ROOT

        roles_dir = str(PROJECT_ROOT / "roles")
        found = []

        for root, dirs, files in os.walk(roles_dir):  # nocheck: project-walk
            # Skip __pycache__ folders
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for file in files:
                if file.endswith(".pyc"):
                    continue
                file_path = str(Path(root) / file)
                # Skip this test file itself (so it can contain the pattern in docstrings)
                if str(Path(file_path).resolve()) == str(Path(__file__).resolve()):
                    continue
                try:
                    with Path(file_path).open(encoding="utf-8") as f:
                        for lineno, line in enumerate(f, 1):
                            match = self.APPLICATIONS_VARIABLE_PATTERN.search(line)
                            if match:
                                found.append(f"{file_path}:{lineno}: {line.strip()}")
                except Exception:
                    # Binary or unreadable file, skip
                    continue

        if found:
            self.fail(
                "Found illegal usages of 'applications[variable]' in the following locations:\n"
                + "\n".join(found)
                + "\n\nPlease use utils.roles.applications.config.get instead."
            )


if __name__ == "__main__":
    unittest.main()
