"""A link between pulled custom-role files needs no git tracking; any other untracked target does."""

from __future__ import annotations

import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

from tests.lint.repository.documentation import test_markdown_links as links

CUSTOM_SOURCE = "roles/web-app-cst-demo/README.md"
CORE_SOURCE = "docs/index.md"
CUSTOM_TARGET = "roles/web-app-cst-demo/meta/services.yml"
GENERATED_TARGET = "docs/generated/page.md"


class TestUntrackedLinkTargets(unittest.TestCase):
    def setUp(self) -> None:
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        for patcher in (
            unittest.mock.patch.object(links, "PROJECT_ROOT", self.root),
            unittest.mock.patch.object(
                links, "_tracked_files", return_value=frozenset()
            ),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def _reason(self, target: str, source: str) -> str:
        path = self.root / target
        path.parent.mkdir(parents=True)
        path.write_text("", encoding="utf-8")
        return links._unresolvable(path, self.root / source)

    def test_custom_role_target_from_custom_role_page_resolves(self) -> None:
        self.assertEqual("", self._reason(CUSTOM_TARGET, CUSTOM_SOURCE))

    def test_untracked_target_outside_custom_roles_reports_untracked(self) -> None:
        self.assertIn("untracked", self._reason(GENERATED_TARGET, CUSTOM_SOURCE))

    def test_custom_role_target_from_tracked_page_reports_untracked(self) -> None:
        self.assertIn("untracked", self._reason(CUSTOM_TARGET, CORE_SOURCE))


if __name__ == "__main__":
    unittest.main()
