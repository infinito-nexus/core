import io
import re
import unittest
from typing import ClassVar

from PIL import Image

from utils.design.logo import (
    LAYOUT_LOGO,
    LAYOUT_LOGO_STACKED,
    LAYOUT_LOGO_TITLE,
    LAYOUT_LOGO_TITLE_DOMAIN,
    LAYOUT_TITLE,
    choose_layout,
    render_assets,
)

from . import PROJECT_ROOT

LOGO = str(PROJECT_ROOT / "assets" / "img" / "logo.png")
TEXT_RE = re.compile(r"<text ([^>]*)>([^<]*)</text>")


class TestChooseLayout(unittest.TestCase):
    def test_slot_format_picks_the_lockup(self) -> None:
        cases = {
            (512, 512, False): LAYOUT_LOGO,
            (320, 64, False): LAYOUT_LOGO_TITLE,
            (720, 64, False): LAYOUT_LOGO_TITLE_DOMAIN,
            (960, 160, False): LAYOUT_LOGO_STACKED,
            (320, 64, True): LAYOUT_TITLE,
        }
        for (width, height, text_only), expected in cases.items():
            with self.subTest(width=width, height=height, text_only=text_only):
                self.assertEqual(
                    choose_layout(width, height, text_only, True), expected
                )

    def test_without_title_every_logo_slot_shows_the_logo_only(self) -> None:
        self.assertEqual(choose_layout(960, 160, False, False), LAYOUT_LOGO)


class TestRenderAssets(unittest.TestCase):
    SLOTS: ClassVar[dict] = {
        "icon": {"width": 512, "height": 512, "text_only": False, "frame": False},
        "header": {"width": 320, "height": 64, "text_only": False, "frame": False},
        "banner": {"width": 960, "height": 160, "text_only": False, "frame": False},
        "wordmark": {"width": 320, "height": 64, "text_only": True, "frame": False},
        "topbar": {"width": 320, "height": 64, "text_only": False, "frame": True},
    }
    COLORS: ClassVar[tuple] = ("#001f3f", "#ffffff", "#fefefe", "#00152c")

    def test_every_slot_renders_png_and_svg_at_its_size(self) -> None:
        assets = render_assets(
            LOGO, "Gitea", "git.example.org", *self.COLORS, self.SLOTS
        )
        for name, spec in self.SLOTS.items():
            with self.subTest(slot=name):
                image = Image.open(io.BytesIO(assets[f"{name}.png"]))
                self.assertEqual(image.size, (spec["width"], spec["height"]))
                self.assertEqual(image.mode, "RGBA")
                self.assertEqual(image.getpixel((0, 0))[3], 0)
                svg = assets[f"{name}.svg"].decode("utf-8")
                self.assertIn(f'width="{spec["width"]}" height="{spec["height"]}"', svg)
                self.assertTrue(svg.endswith("</svg>"))

    def test_text_carries_fill_and_outline(self) -> None:
        assets = render_assets(
            LOGO, "Gitea", "git.example.org", *self.COLORS, self.SLOTS
        )
        texts = TEXT_RE.findall(assets["banner.svg"].decode("utf-8"))
        self.assertEqual(
            [content for _, content in texts], ["Gitea", "git.example.org"]
        )
        for attrs, _ in texts:
            self.assertIn('fill="#001f3f"', attrs)
            self.assertIn('stroke="#ffffff"', attrs)
            self.assertIn("textLength=", attrs)

    def test_frame_slot_takes_the_frame_colors(self) -> None:
        assets = render_assets(
            LOGO, "Gitea", "git.example.org", *self.COLORS, self.SLOTS
        )
        texts = TEXT_RE.findall(assets["topbar.svg"].decode("utf-8"))
        self.assertEqual([content for _, content in texts], ["Gitea"])
        for attrs, _ in texts:
            self.assertIn('fill="#fefefe"', attrs)
            self.assertIn('stroke="#00152c"', attrs)
        self.assertNotEqual(assets["topbar.png"], assets["header.png"])

    def test_favicon_holds_every_size(self) -> None:
        assets = render_assets(
            LOGO, "Gitea", "git.example.org", *self.COLORS, self.SLOTS
        )
        icon = Image.open(io.BytesIO(assets["favicon.ico"]))
        self.assertEqual(icon.info["sizes"], {(16, 16), (32, 32), (48, 48), (64, 64)})

    def test_disabled_title_drops_text_only_slots_and_text(self) -> None:
        assets = render_assets(LOGO, False, "git.example.org", *self.COLORS, self.SLOTS)
        self.assertNotIn("wordmark.png", assets)
        self.assertNotIn(b"<text", assets["banner.svg"])


if __name__ == "__main__":
    unittest.main()
