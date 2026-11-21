from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.routines import design
from agents.routines.tools import gallery


class TestCollect(unittest.TestCase):
    def test_every_named_app_gets_its_manifest_and_gaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            after = Path(tmp) / "web-app-gitea" / "after"
            after.mkdir(parents=True)
            (after / "home-light-desktop.png").write_bytes(b"\x89PNG")
            with patch.object(gallery, "GALLERY_ROOT", Path(tmp)):
                state = gallery.collect({"apps": ["web-app-gitea", "web-app-none"]})
        self.assertEqual(
            state["gallery"],
            {
                "web-app-gitea": {
                    "manifest": {"after": {"home": ["light-desktop"]}},
                    "gaps": [],
                },
                "web-app-none": {"manifest": {}, "gaps": []},
            },
        )

    def test_a_state_without_apps_collects_nothing(self) -> None:
        self.assertEqual(gallery.collect({})["gallery"], {})

    def test_an_app_outside_the_root_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            gallery.collect({"apps": ["../x"]})


class TestDesignerUsesTheSharedGallery(unittest.TestCase):
    def test_the_gallery_step_runs_the_shared_node(self) -> None:
        (step,) = [step for step in design.STEPS if step.id == "D6"]
        self.assertIs(step.fn, gallery.collect)
        self.assertIn(gallery.GALLERY_COMMAND, step.label)
        self.assertIn(gallery.MANIFEST_COMMAND, step.label)


if __name__ == "__main__":
    unittest.main()
