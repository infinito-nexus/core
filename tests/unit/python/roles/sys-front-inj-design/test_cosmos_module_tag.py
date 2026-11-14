from __future__ import annotations

import json
import unittest
from html.parser import HTMLParser
from unittest import mock

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template

from plugins.lookup.cdn import SAME_ORIGIN_PATH, _cdn_paths, _to_url_tree
from utils.cache.files import PROJECT_ROOT, read_text
from utils.domains.default_primary import default_domain_primary

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))

COSMOS = "web-app-cst-cosmos"
APP = "web-svc-html"
HEAD = PROJECT_ROOT / "roles" / "sys-front-inj-design" / "templates" / "head_sub.j2"
DOMAIN = default_domain_primary()
ZONE = "Europe/Berlin"
ONION = "a" * 56 + ".onion"
CDN_ROOT = "/nonexistent/infinito/cdn"
MTIME = "7"
MODULE = f"{SAME_ORIGIN_PATH}/roles/{COSMOS}/latest/js/cosmos.js?v={MTIME}"
LIBRARY = f"roles/{COSMOS}/files/javascript/cosmos.js"
HOSTILE_HOTKEY = "alt+'\"></script><img src=x onerror=alert(1)>"


class _Stub(LookupBase):
    def __init__(self, name, answer, calls):
        super().__init__()
        self._name = name
        self._answer = answer
        self._calls = calls

    def run(self, terms, variables=None, **kwargs):
        self._calls.append((self._name, tuple(terms)))
        return [self._answer(*terms, **kwargs)]


class _Modules(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.found: list[dict] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "script" and attributes.get("type") == "module":
            self.found.append(attributes)


def _cdn(application_id):
    paths = _cdn_paths(CDN_ROOT, application_id, "latest")
    return {
        **paths,
        "urls": _to_url_tree(paths, paths["root"], f"https://cdn.{DOMAIN}"),
        "relative_urls": _to_url_tree(paths, paths["root"], SAME_ORIGIN_PATH),
    }


def _config(services):
    def answer(application_id, path, *default):
        if application_id != COSMOS:
            raise AssertionError(f"head_sub read the config of {application_id}")
        if path in services:
            return services[path]
        if default:
            return default[0]
        raise KeyError(path)

    return answer


def _unexpected(name):
    def answer(*terms, **_kwargs):
        raise AssertionError(f"head_sub called lookup('{name}', {terms!r})")

    return answer


def render(provider, vhost, services=None):
    """
    Args:
        provider: the role ``lookup('design', app).cosmos`` returns, or "".
        vhost: the vhost being rendered.
        services: the ``applications.web-app-cst-cosmos`` config paths.

    Returns:
        ``(html, calls)``: the rendered head and every ``(lookup, terms)`` call.
    """
    calls: list[tuple[str, tuple]] = []
    answers = {
        "design": lambda _app: {"bootstrap": False, "cosmos": provider},
        "cdn": _cdn,
        "path_absolute": lambda *parts: "/".join(parts),
        "local_mtime_qs": lambda _path, param="version": f"?{param}={MTIME}",
        "config": _config(services or {}),
        "domain": _unexpected("domain"),
        "domains": _unexpected("domains"),
        "tls": _unexpected("tls"),
    }
    real_get = lookup_loader.get

    def get(name, *args, **kwargs):
        if name in answers:
            return _Stub(name, answers[name], calls)
        return real_get(name, *args, **kwargs)

    variables = {
        "application_id": APP,
        "group_names": [APP],
        "domain": vhost,
        "DOMAIN_PRIMARY": DOMAIN,
        "HOST_TIMEZONE": ZONE,
        "app_style_present": False,
        "design_js_one_liner": "",
        "design_config_json": "",
    }
    templar = Templar(loader=DataLoader(), variables=variables)
    with mock.patch.object(lookup_loader, "get", side_effect=get):
        html = templar.template(trust_as_template(read_text(str(HEAD))))
    return html, calls


def modules(html):
    parser = _Modules()
    parser.feed(html)
    return parser.found


def cosmos_config(html):
    return json.loads(modules(html)[0]["data-cosmos"])


class TestACosmosHostLoadsTheModule(unittest.TestCase):
    def test_the_module_loads_same_origin_with_a_cache_buster(self) -> None:
        html, calls = render(COSMOS, f"html.{DOMAIN}")
        self.assertEqual([tag["src"] for tag in modules(html)], [MODULE])
        self.assertIn(("local_mtime_qs", (LIBRARY,)), calls)

    def test_the_config_carries_the_host_zone_and_the_parent_cookie_domain(
        self,
    ) -> None:
        html, _calls = render(COSMOS, f"html.{DOMAIN}")
        self.assertEqual(cosmos_config(html), {"zone": ZONE, "cookieDomain": DOMAIN})

    def test_the_primary_domain_itself_shares_the_parent_cookie_domain(self) -> None:
        html, _calls = render(COSMOS, DOMAIN)
        self.assertEqual(cosmos_config(html), {"zone": ZONE, "cookieDomain": DOMAIN})

    def test_a_vhost_outside_the_primary_domain_gets_a_host_only_cookie(self) -> None:
        for vhost in (f"html.{ONION}", "html.example.org", f"html-{DOMAIN}"):
            with self.subTest(vhost=vhost):
                html, _calls = render(COSMOS, vhost)
                self.assertEqual(cosmos_config(html), {"zone": ZONE})

    def test_a_configured_hotkey_reaches_the_config_and_an_unset_one_stays_out(
        self,
    ) -> None:
        html, _calls = render(
            COSMOS, f"html.{DOMAIN}", {"services.cosmos.hotkey": "ctrl+alt+k"}
        )
        self.assertEqual(cosmos_config(html)["hotkey"], "ctrl+alt+k")
        html, _calls = render(COSMOS, f"html.{DOMAIN}")
        self.assertNotIn("hotkey", cosmos_config(html))

    def test_a_hostile_hotkey_survives_the_attribute(self) -> None:
        services = {"services.cosmos.hotkey": HOSTILE_HOTKEY}
        html, _calls = render(COSMOS, f"html.{DOMAIN}", services)
        self.assertEqual(len(modules(html)), 1)
        self.assertEqual(cosmos_config(html)["hotkey"], HOSTILE_HOTKEY)
        self.assertNotIn("<img", html)


class TestARoleWithoutAnActiveProviderStaysAsItWas(unittest.TestCase):
    def test_no_module_tag_is_rendered(self) -> None:
        html, _calls = render("", f"html.{DOMAIN}")
        self.assertEqual(modules(html), [])
        self.assertNotIn("data-cosmos", html)

    def test_no_lookup_names_the_reserved_role(self) -> None:
        _html, calls = render("", f"html.{DOMAIN}")
        self.assertEqual([call for call in calls if COSMOS in call[1]], [])


if __name__ == "__main__":
    unittest.main()
