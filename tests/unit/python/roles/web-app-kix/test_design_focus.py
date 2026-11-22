from __future__ import annotations

import re
import unittest

from utils.cache.files import read_text

from . import PROJECT_ROOT

STYLESHEET = PROJECT_ROOT / "roles" / "web-app-kix" / "files" / "style.css"
RULE = re.compile(r"([^{}]+)\{([^{}]*)\}")


def _rules() -> list[tuple[frozenset[str], dict[str, str]]]:
    """
    Returns:
        One entry per rule: its selectors and its declarations by property.
    """
    rules = []
    for selectors, body in RULE.findall(read_text(str(STYLESHEET))):
        names = frozenset(" ".join(s.split()) for s in selectors.split(","))
        declarations = {}
        for declaration in body.split(";"):
            name, _, value = declaration.partition(":")
            if value:
                declarations[name.strip()] = value.strip()
        rules.append((names, declarations))
    return rules


def _declared(selector: str, prop: str) -> list[str]:
    """
    Args:
        selector: a selector of the rule, whitespace collapsed.
        prop: the property name.

    Returns:
        Every value declared for it, in stylesheet order.
    """
    return [
        declarations[prop]
        for selectors, declarations in _rules()
        if selector in selectors and prop in declarations
    ]


class TestDesignFocus(unittest.TestCase):
    def test_kix_focus_colors_take_the_tokens(self) -> None:
        self.assertIn("var(--design-link-rgb)", _declared(":root", "--focus-color"))
        self.assertIn(
            "var(--design-on-frame-rgb)",
            _declared(":root", "--focus-color-alternative"),
        )

    def test_the_ring_follows_the_focus_token_of_its_frame(self) -> None:
        for selector in (":root :focus", ":root :focus-within"):
            with self.subTest(selector=selector):
                self.assertIn(
                    "2px solid var(--design-focus, var(--design-link))",
                    _declared(selector, "--focus-outline"),
                )

    def test_the_skip_link_sits_on_the_frame(self) -> None:
        self.assertIn(
            "var(--design-frame)",
            _declared("#kix-header .skip-to-main", "background-color"),
        )
        self.assertIn(
            "var(--design-on-frame)",
            _declared("#kix-header .skip-to-main", "color"),
        )


if __name__ == "__main__":
    unittest.main()
