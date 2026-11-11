import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.design.film_theme import (
    MONO_FONT,
    THEME_TOKENS,
    design_spot,
    render,
    theme,
)
from utils.design.palette import build_palette
from utils.roles.mapping import ROLE_FILE_META_SERVICES

SERVICES = PROJECT_ROOT / "roles" / "web-svc-design" / ROLE_FILE_META_SERVICES
SKILLS = PROJECT_ROOT / "agents" / "skills"
TEMPLATES = (
    SKILLS / "i8-release-article" / "templates" / "banner.svg",
    SKILLS / "i8-release-instagram" / "templates" / "instagram.svg",
)
COLOUR_LITERAL = re.compile(r'="#[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3})?"')
THEME_PLACEHOLDER = re.compile(r"\{\{(?:BG2?|INK[23]?|ACCENT2?|SANS|MONO|LOGO)\}\}")


class TestTheme(unittest.TestCase):
    def setUp(self) -> None:
        self.spot = load_yaml_any(str(SERVICES))["design"]
        self.dark = build_palette(self.spot["colors"]["base"])["dark"]
        self.tokens = theme(design_spot())

    def test_every_contract_token_is_set(self) -> None:
        self.assertEqual(
            sorted(token for token in self.tokens if token.startswith("--")),
            sorted(THEME_TOKENS),
        )

    def test_colours_come_from_the_dark_palette_of_the_base(self) -> None:
        expected = {
            "--bg": self.dark["--design-surface-1"],
            "--bg2": self.dark["--design-surface-2"],
            "--ink": self.dark["--design-text"],
            "--ink2": self.dark["--design-text-muted"],
            "--ink3": self.dark["--design-border-strong"],
            "--accent": self.dark["--design-primary"],
            "--accent2": self.dark["--design-link"],
        }
        self.assertEqual({k: self.tokens[k] for k in expected}, expected)

    def test_fonts_come_from_the_design_font(self) -> None:
        self.assertEqual(self.tokens["--sans"], self.spot["font"]["type"])
        self.assertEqual(self.tokens["--mono"], MONO_FONT)

    def test_logo_is_the_design_logo(self) -> None:
        logo = Path(self.tokens["logo"])
        self.assertEqual(logo, PROJECT_ROOT / "assets" / "img" / "logo.png")
        self.assertTrue(logo.is_file())

    def test_another_base_changes_the_colours(self) -> None:
        other = theme({**self.spot, "colors": {"base": "#7a1f00"}})
        self.assertNotEqual(other["--accent"], self.tokens["--accent"])


class TestRender(unittest.TestCase):
    def setUp(self) -> None:
        self.tokens = theme(design_spot())

    def test_fills_theme_placeholders_and_keeps_content_ones(self) -> None:
        out = render('<t fill="{{ACCENT}}">{{VERSION}}</t>', self.tokens)
        self.assertEqual(
            out, f'<t fill="{self.tokens["--accent"]}">{{{{VERSION}}}}</t>'
        )

    def test_quotes_in_a_font_stack_are_escaped(self) -> None:
        out = render('<t font-family="{{SANS}}"/>', self.tokens)
        self.assertNotIn('"Segoe UI"', out)
        self.assertIn("&quot;Segoe UI&quot;", out)

    def test_logo_becomes_a_file_url(self) -> None:
        out = render('<image href="{{LOGO}}"/>', self.tokens)
        self.assertIn(Path(self.tokens["logo"]).as_uri(), out)


class TestTemplatesUseTheTheme(unittest.TestCase):
    def test_templates_carry_no_colour_literal(self) -> None:
        for template in TEMPLATES:
            with self.subTest(template=template.name):
                self.assertEqual(COLOUR_LITERAL.findall(read_text(str(template))), [])

    def test_rendered_templates_hold_no_theme_placeholder(self) -> None:
        tokens = theme(design_spot())
        for template in TEMPLATES:
            with self.subTest(template=template.name):
                text = read_text(str(template))
                self.assertTrue(THEME_PLACEHOLDER.search(text))
                self.assertIsNone(THEME_PLACEHOLDER.search(render(text, tokens)))


if __name__ == "__main__":
    unittest.main()
