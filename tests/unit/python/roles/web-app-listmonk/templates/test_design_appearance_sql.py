from __future__ import annotations

import json
import re
import unittest

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from . import PROJECT_ROOT

TEMPLATES = PROJECT_ROOT / "roles/web-app-listmonk/templates"
LOGO_FALLBACK = "https://files.example.com/logo.png"
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


def render(enabled: bool, logo_fallback: str) -> str:
    """
    Args:
        enabled: value of LISTMONK_DESIGN_ENABLED.
        logo_fallback: app.logo_url the role writes while design is off.
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
        "LISTMONK_DESIGN_BRANDING": [
            {
                "key": "app.logo_url",
                "design": DESIGN["urls"]["header"]["svg"],
                "fallback": logo_fallback,
            },
            {
                "key": "app.site_name",
                "design": DESIGN["label"],
                "fallback": "Example Mailing list",
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
        updates = statements(render(enabled=True, logo_fallback=LOGO_FALLBACK))
        for key, marker in (
            ("appearance.admin.custom_css", CSS_MARKER),
            ("appearance.admin.custom_js", JS_MARKER),
            ("appearance.public.custom_css", CSS_MARKER),
        ):
            with self.subTest(key=key):
                self.assertIn(f"to_jsonb($infinito_value${marker}", updates[key])
                self.assertIn(
                    f"starts_with(value #>> '{{}}', $infinito_marker${marker}$infinito_marker$)",
                    updates[key],
                )
                self.assertIn("value IS DISTINCT FROM", updates[key])
        self.assertIn(DESIGN["urls"]["header"]["svg"], updates["app.logo_url"])
        self.assertIn(
            "$infinito_value$Listmonk$infinito_value$", updates["app.site_name"]
        )

    def test_design_off_empties_only_the_marked_values_and_restores_the_fallback(
        self,
    ) -> None:
        updates = statements(render(enabled=False, logo_fallback=LOGO_FALLBACK))
        for key in (
            "appearance.admin.custom_css",
            "appearance.admin.custom_js",
            "appearance.public.custom_css",
        ):
            with self.subTest(key=key):
                self.assertIn(
                    "SET value = to_jsonb($infinito_value$$infinito_value$::text)",
                    updates[key],
                )
                self.assertIn(
                    "starts_with(value #>> '{}', $infinito_marker$", updates[key]
                )
        self.assertIn(
            f"$infinito_value${LOGO_FALLBACK}$infinito_value$", updates["app.logo_url"]
        )
        self.assertIn(
            "$infinito_value$Example Mailing list$infinito_value$",
            updates["app.site_name"],
        )

    def test_design_off_without_fallback_clears_only_the_design_value(self) -> None:
        update = statements(render(enabled=False, logo_fallback=""))["app.logo_url"]
        self.assertIn(
            f"AND value = to_jsonb($infinito_value${DESIGN['urls']['header']['svg']}",
            update,
        )

    def test_the_carried_css_holds_no_literal_color(self) -> None:
        sql = render(enabled=True, logo_fallback=LOGO_FALLBACK)
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
