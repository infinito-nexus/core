from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from cli.meta.roles.design.propose import main
from utils.design.proposal import PROPOSAL_FILE, proposed_apps


class TestProposeCli(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "web-app-gitea" / "after").mkdir(parents=True)
        patcher = patch("cli.meta.roles.design.propose.GALLERY_ROOT", self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _run(self, argv: list[str]) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_a_proposal_queues_the_app(self) -> None:
        code, out, _ = self._run(["web-app-gitea", "--finding", "a", "--finding", "b"])
        self.assertEqual(
            (code, out), (0, f"{self.root / 'web-app-gitea' / PROPOSAL_FILE}\n")
        )
        self.assertEqual(proposed_apps(self.root), frozenset({"web-app-gitea"}))

    def test_an_uncaptured_or_foreign_app_exits_two(self) -> None:
        for app in ("web-app-none", "../web-app-gitea"):
            with self.subTest(app=app):
                code, out, err = self._run([app, "--finding", "a"])
                self.assertEqual((code, out), (2, ""))
                self.assertIn("[ERROR]", err)
        self.assertEqual(proposed_apps(self.root), frozenset())


if __name__ == "__main__":
    unittest.main()
