from __future__ import annotations

import json
import re
import unittest
from html.parser import HTMLParser

from ansible.module_utils.parsing.convert_bool import boolean
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from utils.cache.yaml import load_yaml, load_yaml_any
from utils.i18n.extract import logout_context
from utils.i18n.keyed import keyed_catalogue
from utils.roles.mapping import ROLE_FILE_META_SERVICES, ROLE_FILE_VARS_MAIN

from . import PROJECT_ROOT

ROLE = PROJECT_ROOT / "roles" / "web-app-keycloak"
DASHBOARD = PROJECT_ROOT / "roles" / "web-app-dashboard"
TEMPLATE = "theme/login/logout-confirm.ftl.j2"
CATALOGUE = keyed_catalogue(
    PROJECT_ROOT,
    logout_context,
    load_yaml(ROLE / "files" / "logout_i18n.yml"),
    PROJECT_ROOT,
    "core",
)
DASHBOARD_LANDING = "https://dashboard.example.com/"
MARKER = load_yaml_any(str(DASHBOARD / ROLE_FILE_META_SERVICES))["sso"]["oidc"][
    "logout_everywhere"
]
EVERYWHERE = DASHBOARD_LANDING + MARKER
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


def everywhere_url(dashboard_deployed: bool, dashboard_oidc: bool) -> str:
    """Render KEYCLOAK_LOGOUT_EVERYWHERE_URL from the role's vars.

    Args:
        dashboard_deployed: whether web-app-dashboard is part of the deployment.
        dashboard_oidc: the dashboard's services.sso.enabled.
    """
    answers = {
        ("web-app-keycloak", "services.dashboard.enabled"): dashboard_deployed,
        ("web-app-dashboard", "services.sso.enabled"): dashboard_oidc,
        ("web-app-dashboard", "services.sso.oidc.logout_everywhere"): MARKER,
    }

    def lookup(name, *args, **_kwargs):
        if name == "config":
            return answers[args]
        if name == "landing_url" and args == ("web-app-dashboard",):
            return DASHBOARD_LANDING
        raise AssertionError(f"unexpected lookup {name}{args}")

    env = Environment(undefined=StrictUndefined, autoescape=select_autoescape())
    env.filters["bool"] = lambda value: boolean(value, strict=False)
    role_vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
    context = {"lookup": lookup, "application_id": "web-app-keycloak"}
    context["KEYCLOAK_LOGOUT_EVERYWHERE_ENABLED"] = env.from_string(
        role_vars["KEYCLOAK_LOGOUT_EVERYWHERE_ENABLED"]
    ).render(context)
    return env.from_string(role_vars["KEYCLOAK_LOGOUT_EVERYWHERE_URL"]).render(context)


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

    def test_the_dashboard_with_oidc_offers_everywhere_on_its_landing_url(
        self,
    ) -> None:
        self.assertEqual(everywhere_url(True, True), EVERYWHERE)

    def test_no_dashboard_or_a_dashboard_without_oidc_offers_no_everywhere(
        self,
    ) -> None:
        for deployed, oidc in ((False, True), (True, False), (False, False)):
            with self.subTest(dashboard_deployed=deployed, dashboard_oidc=oidc):
                url = everywhere_url(deployed, oidc)
                self.assertEqual(url, "")
                self.assertNotIn("kc-logout-everywhere", elements(render(url)))

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
