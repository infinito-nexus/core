from __future__ import annotations

import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-n8n"
SLOTS = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))["design"]["slots"]
DESIGN = {
    "logo": "/opt/design/logo.svg",
    "title": "n8n",
    "slots": SLOTS,
    "urls": {
        "brand": {"svg": "https://cdn.example.test/design/brand.svg"},
        "logo": {"svg": "https://cdn.example.test/design/logo.svg"},
    },
}
SOLID = '.button[class*="_solid_"]'
BRAND = '.button[class*="_brand_"]'
LOGO = '[data-test-id="n8n-logo"]'
SIDEBAR_LOGO = f"#sidebar {LOGO}"
ON_PRIMARY = "var(--design-on-primary)"
N8N_LENGTHS = {
    "--height--3xs": 16.0,
    "--height--md": 32.0,
    "--spacing--3xs": 6.0,
    "--spacing--4xs": 4.0,
}
N8N_LOGO_ICON_VIEWBOX = (240, 96)
N8N_LOGO_TEXT_VIEWBOX = (168, 96)
N8N_GLYPH_BOX_HEIGHT = N8N_LENGTHS["--height--3xs"]
N8N_GLYPH_BOX_WIDTH = (
    N8N_GLYPH_BOX_HEIGHT * N8N_LOGO_ICON_VIEWBOX[0] / N8N_LOGO_ICON_VIEWBOX[1]
    + N8N_LENGTHS["--spacing--3xs"]
    + N8N_GLYPH_BOX_HEIGHT * N8N_LOGO_TEXT_VIEWBOX[0] / N8N_LOGO_TEXT_VIEWBOX[1]
)
LOCKUP_TITLE_FONT_SIZE = 35.0
SIDEBAR_ENTRY_FONT_SIZE = 14.0
TOKEN = re.compile(r"[*/]|\d+(?:\.\d+)?")


def render() -> str:
    """
    Returns:
        The role stylesheet rendered for a role that replaces logo and title.
    """
    environment = Environment(
        loader=FileSystemLoader(str(ROLE / "templates")),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    environment.globals["lookup"] = lambda plugin, application_id: DESIGN
    return environment.get_template("style.css.j2").render(application_id="web-app-n8n")


def declarations(css: str, selector: str) -> dict[str, str] | None:
    """
    Args:
        css: rendered stylesheet.
        selector: one selector of a rule's selector list.

    Returns:
        The declarations of the first rule whose selector list carries the selector, or None when no rule carries it.
    """
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        if selector in (entry.strip() for entry in selectors.split(",")):
            pairs = [
                declaration.split(":", 1)
                for declaration in body.split(";")
                if declaration.strip()
            ]
            return {name.strip(): value.strip() for name, value in pairs}
    return None


def pixels(expression: str) -> float:
    """
    Args:
        expression: a length of n8n 3.3 heights and spacings, either one var() or a calc() of a sum of products and quotients.

    Returns:
        The length in CSS pixels.
    """
    for name, value in N8N_LENGTHS.items():
        expression = expression.replace(f"var({name})", str(value))
    total = 0.0
    for term in expression.split("+"):
        tokens = TOKEN.findall(term)
        result = float(tokens[0])
        for operator, operand in zip(tokens[1::2], tokens[2::2], strict=True):
            result = (
                result * float(operand) if operator == "*" else result / float(operand)
            )
        total += result
    return total


def sidebar_lockup(css: str) -> dict[str, float]:
    """
    Args:
        css: rendered stylesheet.

    Returns:
        The box of the expanded sidebar logo, the size the lockup is painted at in it and the painted size of the lockup title, the way the design spec measures them. Without a size of its own the box wraps the two hidden 16px glyphs of n8n 3.
    """
    background = declarations(css, LOGO)["background"]
    overscale = float(re.search(r"auto (\d+)%", background).group(1)) / 100
    own = declarations(css, SIDEBAR_LOGO) or {}
    box_height = pixels(own["height"]) if "height" in own else N8N_GLYPH_BOX_HEIGHT
    painted_height = box_height * overscale
    brand = SLOTS["brand"]
    return {
        "box_width": pixels(own["width"]) if "width" in own else N8N_GLYPH_BOX_WIDTH,
        "box_height": box_height,
        "painted_width": painted_height * brand["width"] / brand["height"],
        "painted_height": painted_height,
        "title": LOCKUP_TITLE_FONT_SIZE * painted_height / brand["height"],
    }


class TestStyleCss(unittest.TestCase):
    def setUp(self) -> None:
        self.css = render()

    def test_the_brand_button_n8n_3_renders_for_the_create_action_letters_in_the_on_primary_color_like_the_solid_one(
        self,
    ) -> None:
        for selector in (SOLID, BRAND):
            with self.subTest(selector=selector):
                rule = declarations(self.css, selector) or {}
                self.assertEqual(rule.get("--button--color"), ON_PRIMARY)

    def test_the_lockup_title_in_the_expanded_sidebar_is_not_smaller_than_the_entries_and_the_lockup_fits_its_box(
        self,
    ) -> None:
        lockup = sidebar_lockup(self.css)
        self.assertGreaterEqual(lockup["title"], SIDEBAR_ENTRY_FONT_SIZE)
        self.assertLessEqual(lockup["painted_width"], lockup["box_width"])
        shown_height = min(lockup["painted_height"], lockup["box_height"])
        self.assertGreaterEqual(
            min(lockup["painted_width"], lockup["box_width"]), 2 * shown_height
        )


if __name__ == "__main__":
    unittest.main()
