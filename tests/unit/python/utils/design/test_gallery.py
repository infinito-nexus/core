from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from utils.design.gallery import GALLERY_ROOT, app_gallery, gaps, manifest


def _shoot(gallery: Path, side: str, *names: str) -> None:
    folder = gallery / side
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_bytes(b"\x89PNG")


class TestAppGallery(unittest.TestCase):
    def test_an_application_id_maps_below_the_root(self) -> None:
        self.assertEqual(
            app_gallery(GALLERY_ROOT, "web-app-gitea"), GALLERY_ROOT / "web-app-gitea"
        )

    def test_a_path_that_leaves_the_root_is_refused(self) -> None:
        for app in ("../etc", "web-app-gitea/..", "", "Web-App", "/tmp", "a--b"):
            with self.subTest(app=app), self.assertRaises(ValueError):
                app_gallery(GALLERY_ROOT, app)


class TestManifest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.gallery = Path(tmp.name)

    def test_shots_group_by_side_and_view(self) -> None:
        _shoot(
            self.gallery,
            "after",
            "admin-settings-dark-desktop.png",
            "admin-settings-light-desktop.png",
            "home-light-mobile.png",
        )
        _shoot(self.gallery, "before", "home-light-mobile.png")
        self.assertEqual(
            manifest(self.gallery),
            {
                "after": {
                    "admin-settings": ["dark-desktop", "light-desktop"],
                    "home": ["light-mobile"],
                },
                "before": {"home": ["light-mobile"]},
            },
        )

    def test_files_outside_the_naming_scheme_are_left_out(self) -> None:
        _shoot(self.gallery, "after", "home.png", "-light-desktop.png")
        (self.gallery / "after" / "home-light-desktop.txt").write_text("x")
        self.assertEqual(manifest(self.gallery), {"after": {}})

    def test_an_uncaptured_gallery_is_empty(self) -> None:
        self.assertEqual(manifest(self.gallery / "absent"), {})


class TestGaps(unittest.TestCase):
    def test_a_view_missing_a_shot_of_its_side_is_named(self) -> None:
        shots = {
            "after": {
                "home": ["dark-desktop", "light-desktop"],
                "login": ["light-desktop"],
            },
            "before": {"home": ["light-desktop"]},
        }
        self.assertEqual(gaps(shots), ["after/login: missing dark-desktop"])

    def test_a_complete_gallery_has_no_gaps(self) -> None:
        self.assertEqual(gaps({"after": {"home": ["light-desktop"]}, "x": {}}), [])


if __name__ == "__main__":
    unittest.main()
