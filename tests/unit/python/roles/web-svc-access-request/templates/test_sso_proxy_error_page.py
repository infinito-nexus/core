from __future__ import annotations

import json
import re
import unittest
import urllib.parse

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from plugins.filter.text_filters import to_inline_js
from utils.cache.yaml import load_yaml

from . import PROJECT_ROOT

TEMPLATE = "roles/web-svc-access-request/templates/sso_proxy/error.html.j2"
SOURCE = load_yaml(
    str(PROJECT_ROOT / "roles/web-svc-access-request/files/access_request_i18n.yml")
)
OAUTH2_PROXY_FORBIDDEN = "You do not have permission to access this resource."
SERVICE_URL = "https://access.example.com/"
REQUEST_LINK = re.compile(r'id="request-access" href="([^"]+)"')
CATALOGUE = re.compile(r"var catalogue = (\{.*?\});")
BUTTON = re.compile(r"<button([^>]*)>([^<]*)</button>")
I18N_KEY = re.compile(r'data-i18n="([^"]+)"')


def _render(role: str = "") -> str:
    """Render the oauth2-proxy 403 page of one gated application.

    Args:
        role: the role id the request page preselects.
    """
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(),
    )
    texts = {
        "en": {**SOURCE, "dir": "ltr"},
        "ar": {**{key: f"ar:{key}" for key in SOURCE}, "dir": "rtl"},
    }

    def lookup(name: str, *terms, **_kwargs):
        if name == "i18n_catalogue" and terms[0] == "access_request":
            return texts
        if (name, *terms) == ("tls", "web-svc-access-request", "url.base"):
            return SERVICE_URL
        raise AssertionError(f"unexpected lookup {name}{terms}")

    env.globals["lookup"] = lookup
    env.filters["combine"] = lambda left, right: {**left, **right}
    env.filters["dict2items"] = lambda mapping: [
        {"key": key, "value": value} for key, value in mapping.items()
    ]
    env.filters["items2dict"] = lambda items: {i["key"]: i["value"] for i in items}
    env.filters["to_inline_js"] = to_inline_js
    return env.get_template(TEMPLATE).render(
        sso_proxy_application_id="web-app-app", access_request_role=role
    )


def _link(rendered: str) -> tuple[str, dict[str, list[str]]]:
    url = REQUEST_LINK.search(rendered).group(1).replace("&amp;", "&")
    base, _, query = url.partition("?")
    return base, urllib.parse.parse_qs(query)


class TestSsoProxyErrorPage(unittest.TestCase):
    def test_the_page_defines_the_template_oauth2_proxy_loads(self):
        self.assertTrue(_render().lstrip().startswith('{{define "error.html"}}'))
        self.assertTrue(_render().rstrip().endswith("{{end}}"))

    def test_only_the_group_refusal_offers_the_request_action(self):
        rendered = _render()
        branch = rendered.index(f'(eq .Message "{OAUTH2_PROXY_FORBIDDEN}")')

        self.assertLess(branch, rendered.index('id="request-access"'))
        self.assertLess(
            rendered.index('id="request-access"'), rendered.index("{{ else }}")
        )

    def test_the_request_action_opens_the_service_with_the_application(self):
        base, query = _link(_render())

        self.assertEqual(SERVICE_URL, base)
        self.assertEqual({"application": ["web-app-app"]}, query)

    def test_a_named_role_is_preselected(self):
        _, query = _link(_render("editor"))

        self.assertEqual(["editor"], query["role"])

    def test_the_inline_catalogue_carries_only_the_page_strings(self):
        catalogue = json.loads(CATALOGUE.search(_render()).group(1))

        self.assertEqual({"en", "ar"}, set(catalogue))
        self.assertEqual(
            {
                "forbidden_title",
                "forbidden_text",
                "forbidden_action",
                "forbidden_back",
                "signin_action",
                "dir",
            },
            set(catalogue["ar"]),
        )
        self.assertEqual("rtl", catalogue["ar"]["dir"])

    def test_every_button_of_the_other_refusals_is_a_catalogue_message(self):
        rendered = _render()
        other = rendered[rendered.index("{{ else }}") :]
        catalogue = json.loads(CATALOGUE.search(rendered).group(1))

        buttons = BUTTON.findall(other)
        self.assertEqual(2, len(buttons))
        for attributes, text in buttons:
            with self.subTest(text=text):
                key = I18N_KEY.search(attributes)
                self.assertIsNotNone(key, f"button {text!r} names no catalogue key")
                self.assertEqual(SOURCE[key.group(1)], text)
                self.assertIn(key.group(1), catalogue["ar"])

    def test_the_language_pick_runs_on_every_branch(self):
        rendered = _render()

        self.assertGreater(
            rendered.index("var catalogue"), rendered.rindex("{{ end }}")
        )


if __name__ == "__main__":
    unittest.main()
