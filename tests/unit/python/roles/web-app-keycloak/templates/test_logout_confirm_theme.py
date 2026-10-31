from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml
from utils.i18n.extract import logout_context
from utils.i18n.keyed import keyed_catalogue

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
TEMPLATE = "theme/login/logout-confirm.ftl.j2"
CATALOGUE = keyed_catalogue(
    PROJECT_ROOT, logout_context, load_yaml(ROLE / "files" / "logout_i18n.yml")
)
EVERYWHERE = "https://dashboard.example.com/#logout-everywhere"
CHOICES_HASH = re.compile(r"<#assign infinitoChoices = (\{.*?\n\})>", re.DOTALL)


class _Elements(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str]] = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if "id" in attributes:
            self.by_id[attributes["id"]] = {"tag": tag, **attributes}


def render(everywhere: str) -> str:
    """Render the corporate theme's confirmation page the way theme.yml stages it.

    Args:
        everywhere: KEYCLOAK_LOGOUT_EVERYWHERE_URL, empty without the dashboard.
    """
    env = Environment(
        loader=FileSystemLoader(str(ROLE / "templates")),
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    env.filters["to_json"] = json.dumps
    return env.get_template(TEMPLATE).render(
        KEYCLOAK_LOGOUT_I18N=CATALOGUE, KEYCLOAK_LOGOUT_EVERYWHERE_URL=everywhere
    )


def elements(source: str) -> dict[str, dict[str, str]]:
    parser = _Elements()
    parser.feed(source)
    return parser.by_id


class TestLogoutConfirmTheme(unittest.TestCase):
    def test_both_choices_are_rendered_server_side(self) -> None:
        found = elements(render(EVERYWHERE))
        self.assertEqual(found["kc-logout"]["tag"], "input")
        self.assertEqual(found["kc-logout"]["type"], "submit")
        self.assertEqual(found["kc-logout"]["name"], "confirmLogout")
        self.assertEqual(found["kc-logout-everywhere"]["tag"], "a")
        self.assertEqual(found["kc-logout-everywhere"]["href"], EVERYWHERE)

    def test_without_the_dashboard_only_this_device_is_offered(self) -> None:
        found = elements(render(""))
        self.assertIn("kc-logout", found)
        self.assertNotIn("kc-logout-everywhere", found)

    def test_the_labels_of_every_language_reach_the_page(self) -> None:
        labels = json.loads(CHOICES_HASH.search(render(EVERYWHERE)).group(1))
        self.assertEqual(set(labels), set(CATALOGUE))
        for code, entry in labels.items():
            with self.subTest(language=code):
                self.assertEqual(
                    entry["choice_device"], CATALOGUE[code]["choice_device"]
                )
                self.assertEqual(
                    entry["choice_everywhere"], CATALOGUE[code]["choice_everywhere"]
                )

    def test_no_label_can_open_a_freemarker_interpolation(self) -> None:
        hash_source = CHOICES_HASH.search(render(EVERYWHERE)).group(1)
        self.assertNotIn("${", hash_source)
        self.assertNotIn("#{", hash_source)


if __name__ == "__main__":
    unittest.main()
