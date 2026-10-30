import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from utils.design.branding import DESIGN_ROLE
from utils.design.preview import build_preview, design_roles, role_domain

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
ROLE = "web-app-gitea"


def _mono_logo(path: Path) -> str:
    image = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
    ImageDraw.Draw(image).ellipse((10, 10, 110, 110), fill="#000000")
    image.save(path)
    return str(path)


class TestDesignRoles(unittest.TestCase):
    def test_lists_design_consumers_without_the_provider(self) -> None:
        roles = design_roles(ROLES_DIR)
        self.assertIn(ROLE, roles)
        self.assertNotIn(DESIGN_ROLE, roles)
        self.assertEqual(roles, sorted(roles))


class TestRoleDomain(unittest.TestCase):
    def test_renders_the_primary_domain_into_the_canonical_domain(self) -> None:
        domain = role_domain(ROLES_DIR, ROLE, "example.org")
        self.assertTrue(domain.endswith(".example.org"), domain)
        self.assertNotIn("{{", domain)

    def test_falls_back_to_the_role_name_without_domains(self) -> None:
        self.assertEqual(
            role_domain(ROLES_DIR, "does-not-exist", "example.org"),
            "does-not-exist.example.org",
        )


class TestBuildPreview(unittest.TestCase):
    def test_writes_every_slot_day_and_night_and_an_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logo = _mono_logo(root / "logo.png")
            index = build_preview(
                logo, "#8DB33A", "example.org", [ROLE], root / "out", PROJECT_ROOT
            )
            html = index.read_text(encoding="utf-8")  # nocheck: cache-read
            role_dir = root / "out" / ROLE
            self.assertIn(ROLE, html)
            self.assertIn("monochrome, recolored per slot", html)
            self.assertNotIn("{{", html)
            self.assertTrue((role_dir / "favicon.ico").is_file())
            pngs = {path.name for path in role_dir.glob("*.png")}
            day = {name for name in pngs if not name.endswith(".night.png")}
            self.assertTrue(day)
            for name in day:
                with self.subTest(slot=name):
                    self.assertIn(f"{ROLE}/{name}", html)
            self.assertTrue(any(name.endswith(".night.png") for name in pngs))


if __name__ == "__main__":
    unittest.main()
