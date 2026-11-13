from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.cache.files import read_text
from utils.design.proposal import PROPOSAL_FILE, file_proposal, proposed_apps


class _GalleryCase(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "design-gallery"
        self.gallery = self.root / "web-app-gitea"
        after = self.gallery / "after"
        after.mkdir(parents=True)
        for name in ("home-light-desktop.png", "home-dark-desktop.png"):
            (after / name).write_bytes(b"\x89PNG")
        (after / "login-light-desktop.png").write_bytes(b"\x89PNG")


class TestFileProposal(_GalleryCase):
    def test_findings_and_gallery_gaps_land_next_to_the_screenshots(self) -> None:
        target = file_proposal(self.gallery, ["header ignores --design-primary"])
        self.assertEqual(target, self.gallery / PROPOSAL_FILE)
        self.assertEqual(
            json.loads(read_text(str(target))),
            {
                "findings": ["header ignores --design-primary"],
                "gaps": ["after/login: missing dark-desktop"],
            },
        )

    def test_a_proposal_without_text_is_refused(self) -> None:
        for findings in ([], [" "], [{"x": 1}]):
            with self.subTest(findings=findings), self.assertRaises(ValueError):
                file_proposal(self.gallery, findings)
        self.assertFalse((self.gallery / PROPOSAL_FILE).exists())

    def test_an_uncaptured_app_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            file_proposal(self.root / "web-app-none", ["x"])

    def test_a_symlinked_gallery_is_refused(self) -> None:
        link = self.root / "web-app-link"
        link.symlink_to(self.gallery)
        with self.assertRaises(ValueError):
            file_proposal(link, ["x"])

    def test_a_planted_symlink_is_never_written_through(self) -> None:
        victim = self.root.parent / "victim"
        victim.write_text("keep", encoding="utf-8")
        (self.gallery / PROPOSAL_FILE).symlink_to(victim)
        with self.assertRaises(ValueError):
            file_proposal(self.gallery, ["x"])
        self.assertEqual(read_text(str(victim)), "keep")

    def test_another_users_gallery_is_refused(self) -> None:
        with (
            patch("utils.design.proposal.os.getuid", return_value=os.getuid() + 1),
            self.assertRaises(ValueError),
        ):
            file_proposal(self.gallery, ["x"])


class TestProposedApps(_GalleryCase):
    def test_an_app_with_a_filed_proposal_is_proposed(self) -> None:
        file_proposal(self.gallery, ["x"])
        self.assertEqual(proposed_apps(self.root), frozenset({"web-app-gitea"}))

    def test_a_gallery_without_a_proposal_is_not_proposed(self) -> None:
        self.assertEqual(proposed_apps(self.root), frozenset())

    def test_a_missing_root_proposes_nothing(self) -> None:
        self.assertEqual(proposed_apps(self.root / "absent"), frozenset())

    def test_a_symlinked_proposal_does_not_count(self) -> None:
        other = self.root / "web-app-other"
        other.mkdir()
        file_proposal(self.gallery, ["x"])
        (other / PROPOSAL_FILE).symlink_to(self.gallery / PROPOSAL_FILE)
        self.assertEqual(proposed_apps(self.root), frozenset({"web-app-gitea"}))

    def test_another_users_proposal_does_not_count(self) -> None:
        file_proposal(self.gallery, ["x"])
        with patch("utils.design.proposal.os.getuid", return_value=os.getuid() + 1):
            self.assertEqual(proposed_apps(self.root), frozenset())


if __name__ == "__main__":
    unittest.main()
