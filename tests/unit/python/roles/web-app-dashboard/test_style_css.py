"""The dashboard stylesheet paints port-ui's frame and accents in the corporate design."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text

STYLE = read_text(
    str(PROJECT_ROOT / "roles" / "web-app-dashboard" / "files" / "style.css")
)
DESIGN_DEFAULTS = read_text(
    str(
        PROJECT_ROOT
        / "roles"
        / "sys-front-inj-design"
        / "templates"
        / "css"
        / "default.css.j2"
    )
)
PRIMARY = "var(--design-primary)"
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_RULE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}")
_DECLARATION = re.compile(r"(?P<property>[-\w]+)\s*:\s*(?P<value>[^;]+);")


def declarations(css: str) -> dict[str, dict[str, str]]:
    """Map every selector of *css* to the declarations its rules set.

    Args:
        css: a flat stylesheet without nested at-rules.

    Returns:
        ``{selector: {property: value}}``, later rules overriding earlier ones.
    """
    result: dict[str, dict[str, str]] = {}
    for rule in _RULE.finditer(_COMMENT.sub("", css)):
        body = {
            match.group("property"): match.group("value").strip()
            for match in _DECLARATION.finditer(rule.group("body"))
        }
        for selector in rule.group("selectors").split(","):
            result.setdefault(" ".join(selector.split()), {}).update(body)
    return result


DECLARED = declarations(STYLE)


class TestDashboardFrame(unittest.TestCase):
    def test_the_frame_surface_tints_the_primary_over_the_page_surface(self) -> None:
        surface = DECLARED[":root"]["--dashboard-frame-surface"]
        self.assertRegex(
            surface,
            r"^color-mix\(in srgb, var\(--design-primary\) \d+%, var\(--design-surface-1\)\)$",
        )
        for selector in (".portui-frame-top", ".portui-frame-bottom"):
            with self.subTest(selector=selector):
                self.assertTrue(
                    DECLARED[selector]["background-color"].startswith(
                        "var(--dashboard-frame-surface)"
                    )
                )

    def test_the_side_borders_and_the_navigation_rules_are_primary(self) -> None:
        self.assertEqual(PRIMARY, DECLARED[":root"]["--portui-frame-border"])
        self.assertIn(PRIMARY, DECLARED[".portui-frame-top nav.navbar"]["border-top"])
        self.assertIn(
            PRIMARY, DECLARED[".portui-frame-bottom nav.navbar"]["border-bottom"]
        )

    def test_the_four_port_ui_shadows_map_to_design_shadow_tokens(self) -> None:
        for name in ("frame", "card", "card-hover", "popup"):
            with self.subTest(shadow=name):
                self.assertRegex(
                    DECLARED[":root"][f"--portui-shadow-{name}"],
                    r"^var\(--design-shadow-\d\)$",
                )


class TestDashboardAccents(unittest.TestCase):
    def test_card_surfaces_stay_neutral(self) -> None:
        self.assertEqual(
            "var(--design-surface-2)", DECLARED[".card"]["background-color"]
        )

    def test_hover_borders_hover_icons_focus_rings_and_the_search_field_are_primary(
        self,
    ) -> None:
        for selector, prop in (
            (".card:hover", "border-color"),
            (".card:focus-within", "border-color"),
            (".card:hover .card-img-top i", "color"),
            (":focus-visible", "outline"),
            ('input[type="search"]:focus', "border-color"),
        ):
            with self.subTest(selector=selector, property=prop):
                self.assertIn(PRIMARY, DECLARED[selector][prop])

    def test_the_badge_accents_take_the_primary_through_bootstrap(self) -> None:
        self.assertIn("--bs-primary: var(--design-primary);", DESIGN_DEFAULTS)
        self.assertIn("--bs-primary-rgb: var(--design-primary-rgb);", DESIGN_DEFAULTS)


class TestDeclarationParser(unittest.TestCase):
    def test_negative_control_a_dropped_accent_is_reported(self) -> None:
        stripped = STYLE.replace(
            "border-color: var(--design-primary);\n}", "border-color: inherit;\n}", 1
        )
        self.assertNotEqual(STYLE, stripped)
        self.assertNotIn(PRIMARY, declarations(stripped)[".card:hover"]["border-color"])


if __name__ == "__main__":
    unittest.main()
