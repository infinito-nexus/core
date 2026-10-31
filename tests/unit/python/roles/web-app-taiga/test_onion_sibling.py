from __future__ import annotations

import re
import unittest
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar
from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.lookup.tls import LookupModule as TlsLookup
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))

ROLE = "web-app-taiga"
ROLE_DIR = PROJECT_ROOT / "roles" / ROLE
VARS = ROLE_DIR / ROLE_FILE_VARS_MAIN
MAIN = ROLE_DIR / ROLE_FILE_TASKS_MAIN
SHEET = ROLE_DIR / "templates" / "design" / "infinito-design.css.j2"

CLEAR = "taiga.kanban.example.test"
ONION = "taiga.kanban." + "a" * 56 + ".onion"
CDN = "https://cdn.example.test"
SAME_ORIGIN = "/_infinito/cdn"
ASSETS = "/roles/web-app-taiga/latest/img/design"
COOKIE_FLAGS = [
    "proxy_cookie_flags sessionid nosecure;",
    "proxy_cookie_flags csrftoken nosecure;",
]
NAMES = ("TAIGA_COOKIE_SECURE", "TAIGA_LOCATION_CONFIGURATION")


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(*terms, **kwargs)]


def resolve(*, siblings, domain, canonical=CLEAR, tls=True) -> dict:
    """Resolve the cookie variables of ``vars/main.yml`` for one vhost.

    Args:
        siblings: the domains the node serves the role on.
        domain: the vhost being rendered.
        canonical: what ``lookup('domain', application_id)`` answers.
        tls: the node's ``TLS_ENABLED``.

    Returns:
        ``{name: value}`` for ``NAMES``, resolved by Ansible's templar with
        the real ``tls`` lookup.
    """
    stubs = {
        "domain": lambda _app: canonical,
        "domains": lambda: {ROLE: siblings},
        "applications": lambda: {ROLE: {}},
    }
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name == "tls":
            lookup = TlsLookup()
            lookup._loader = kwargs.get("loader")
            lookup._templar = None
            return lookup
        if name in stubs:
            return _Stub(stubs[name])
        return real_get(name, *args, **kwargs)

    declared = DataLoader().load_from_file(str(VARS), trusted_as_template=True)
    variables = {"domain": domain, "TLS_ENABLED": tls, "TLS_MODE": "letsencrypt"}
    templar = Templar(loader=DataLoader(), variables={**declared, **variables})
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        return {name: templar.template(declared[name]) for name in NAMES}


def render_logo_rules() -> str:
    source = read_text(str(SHEET))
    block = re.search(
        r"\{% if design\.logo is string %\}.*?\{% endif %\}", source, re.DOTALL
    )
    tree = {slot: {"svg": f"{ASSETS}/{slot}.svg"} for slot in ("logo", "logo-auth")}
    design = {
        "logo": "logo.svg",
        "urls": {slot: {"svg": f"{CDN}{urls['svg']}"} for slot, urls in tree.items()},
        "relative_urls": {
            slot: {"svg": f"{SAME_ORIGIN}{urls['svg']}"} for slot, urls in tree.items()
        },
    }
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return environment.from_string(block.group(0)).render(design=design)


class TestOnionVhost(unittest.TestCase):
    def setUp(self) -> None:
        self.rendered = resolve(siblings=[CLEAR, ONION], domain=ONION)

    def test_the_session_and_csrf_cookies_lose_secure(self) -> None:
        self.assertEqual(
            self.rendered["TAIGA_LOCATION_CONFIGURATION"].splitlines(), COOKIE_FLAGS
        )

    def test_the_backend_still_marks_cookies_secure(self) -> None:
        self.assertEqual(self.rendered["TAIGA_COOKIE_SECURE"], "True")


class TestClearnetVhost(unittest.TestCase):
    def test_the_location_is_unchanged(self) -> None:
        rendered = resolve(siblings=[CLEAR, ONION], domain=CLEAR)
        self.assertEqual(
            (rendered["TAIGA_COOKIE_SECURE"], rendered["TAIGA_LOCATION_CONFIGURATION"]),
            ("True", ""),
        )


class TestNothingToStrip(unittest.TestCase):
    def test_without_tls_the_onion_vhost_is_unchanged(self) -> None:
        rendered = resolve(siblings=[CLEAR, ONION], domain=ONION, tls=False)
        self.assertEqual(
            (rendered["TAIGA_COOKIE_SECURE"], rendered["TAIGA_LOCATION_CONFIGURATION"]),
            ("False", ""),
        )

    def test_a_tor_only_node_is_unchanged(self) -> None:
        rendered = resolve(siblings=[ONION], domain=ONION, canonical=ONION)
        self.assertEqual(
            (rendered["TAIGA_COOKIE_SECURE"], rendered["TAIGA_LOCATION_CONFIGURATION"]),
            ("False", ""),
        )


class TestStackWiring(unittest.TestCase):
    def test_the_proxy_reads_the_location_configuration(self) -> None:
        stack = next(
            task
            for task in load_yaml_any(str(MAIN))
            if task.get("include_role", {}).get("name") == "sys-stk-full"
        )
        self.assertEqual(
            stack["vars"]["webserver_location_extra_configuration"],
            "{{ TAIGA_LOCATION_CONFIGURATION }}",
        )


class TestDesignSheet(unittest.TestCase):
    def setUp(self) -> None:
        self.rules = render_logo_rules()

    def test_the_logos_load_from_the_page_host(self) -> None:
        for slot in ("logo", "logo-auth"):
            with self.subTest(slot=slot):
                self.assertIn(f'url("{SAME_ORIGIN}{ASSETS}/{slot}.svg")', self.rules)

    def test_no_logo_names_an_absolute_host(self) -> None:
        self.assertNotIn("://", self.rules)


if __name__ == "__main__":
    unittest.main()
