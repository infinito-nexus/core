from __future__ import annotations

import json
import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

TEMPLATES = PROJECT_ROOT / "roles/web-app-listmonk/templates"
CSS_MARKER = ":root{--infinito-design-carrier:1}"
JS_MARKER = "window.infinitoDesignCarrier = 1;"
DESIGN = {
    "label": "Listmonk",
    "urls": {
        "favicon_ico": "https://cdn.example.com/design/favicon.ico",
        "header": {"svg": "https://cdn.example.com/design/header.svg"},
        "icon": {"svg": "https://cdn.example.com/design/icon.svg"},
        "logo": {"svg": "https://cdn.example.com/design/logo.svg"},
    },
}
APPEARANCE = (
    ("appearance.admin.custom_css", CSS_MARKER),
    ("appearance.admin.custom_js", JS_MARKER),
    ("appearance.public.custom_css", CSS_MARKER),
)


def render(enabled: bool) -> str:
    """
    Args:
        enabled: value of LISTMONK_DESIGN_ENABLED.
    """
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=select_autoescape(),
    )
    env.filters["bool"] = lambda value: (
        value if isinstance(value, bool) else str(value).lower() == "true"
    )
    env.filters["to_json"] = json.dumps
    context = {
        "LISTMONK_DESIGN": DESIGN,
        "LISTMONK_DESIGN_ENABLED": enabled,
        "LISTMONK_DESIGN_CSS_MARKER": CSS_MARKER,
        "LISTMONK_DESIGN_JS_MARKER": JS_MARKER,
        "LISTMONK_DESIGN_APPEARANCE": [
            {
                "key": "appearance.admin.custom_css",
                "template": "design/admin.css.j2",
                "marker": CSS_MARKER,
            },
            {
                "key": "appearance.admin.custom_js",
                "template": "design/admin.js.j2",
                "marker": JS_MARKER,
            },
            {
                "key": "appearance.public.custom_css",
                "template": "design/public.css.j2",
                "marker": CSS_MARKER,
            },
        ],
    }
    context["lookup"] = lambda kind, name: env.get_template(name).render(context)
    return env.get_template("design/appearance.sql.j2").render(context)


def statements(sql: str) -> dict[str, str]:
    return {
        re.search(r"\nWHERE key = '([^']+)'", statement).group(1): statement
        for statement in sql.split("UPDATE settings\n")[1:]
    }


class TestDesignAppearanceSql(unittest.TestCase):
    def test_design_on_writes_marked_content_only_over_empty_or_own_values(
        self,
    ) -> None:
        updates = statements(render(enabled=True))
        for key, marker in APPEARANCE:
            with self.subTest(key=key):
                self.assertIn(f"to_jsonb($infinito_value${marker}", updates[key])
                self.assertIn(
                    f"starts_with(value #>> '{{}}', $infinito_marker${marker}$infinito_marker$)",
                    updates[key],
                )
                self.assertIn("value IS DISTINCT FROM", updates[key])

    def test_design_off_empties_only_the_marked_values(self) -> None:
        updates = statements(render(enabled=False))
        for key, _marker in APPEARANCE:
            with self.subTest(key=key):
                self.assertIn(
                    "SET value = to_jsonb($infinito_value$$infinito_value$::text)",
                    updates[key],
                )
                self.assertIn(
                    "starts_with(value #>> '{}', $infinito_marker$", updates[key]
                )

    def test_the_branding_settings_are_left_to_the_general_form(self) -> None:
        for enabled in (True, False):
            with self.subTest(enabled=enabled):
                sql = render(enabled=enabled)
                self.assertEqual(
                    {key for key, _marker in APPEARANCE}, set(statements(sql))
                )
                self.assertIn(f"count(*) = {len(APPEARANCE)}", sql)

    def test_the_carried_css_holds_no_literal_color(self) -> None:
        sql = render(enabled=True)
        css = "\n".join(
            statement
            for key, statement in statements(sql).items()
            if key.endswith("custom_css")
        )
        self.assertIsNone(
            re.search(r"#[0-9a-fA-F]{3,8}(?![\w-])", re.sub(r"url\([^)]*\)", "", css))
        )


if __name__ == "__main__":
    unittest.main()
