from __future__ import annotations

import posixpath
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "svc-ai-agent-orchestrator"


def _unstaged_parents(libs: list[str], staged: list[str]) -> list[str]:
    """
    Args:
        libs: files the image copies beside the server.
        staged: directories the role creates before the copy.

    Returns:
        Every file whose parent directory the role never creates.
    """
    created = {
        "/".join(parts[:depth])
        for parts in (directory.split("/") for directory in staged)
        for depth in range(1, len(parts) + 1)
    }
    return [lib for lib in libs if posixpath.dirname(lib) not in created]


class TestEveryStagedLibraryHasItsDirectory(unittest.TestCase):
    def test_every_library_lands_in_a_created_directory(self) -> None:
        variables = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            _unstaged_parents(
                variables["AGENT_ORCHESTRATOR_LIBS"],
                variables["AGENT_ORCHESTRATOR_STAGED_DIRS"],
            ),
            [],
        )

    def test_a_library_outside_the_created_directories_is_reported(self) -> None:
        self.assertEqual(
            _unstaged_parents(
                ["utils/__init__.py", "utils/design/spec.py"],
                ["utils/orchestrator"],
            ),
            ["utils/design/spec.py"],
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
