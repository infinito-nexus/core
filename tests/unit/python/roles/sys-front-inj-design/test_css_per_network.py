"""Every vhost links the role stylesheet rendered for its own network.

``sys-front-inj-all`` runs ``sys-front-inj-design`` once per vhost, and a role
stylesheet such as XWiki's names its own origin through the ``tls`` lookup,
which follows the vhost being rendered. One CDN path for all vhosts let the
last render win: the clearnet document loaded the onion render and requested
onion hosts. The deploy is replayed here vhost by vhost with Ansible's templar,
the real ``tls`` lookup and the real filters, then each vhost's injected link is
followed to the file it names.
"""

from __future__ import annotations

import hashlib
import re
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from ansible.parsing.dataloader import DataLoader
from ansible.plugins.loader import filter_loader, lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import Templar, trust_as_template
from jinja2 import Environment, StrictUndefined, select_autoescape

from plugins.lookup.cdn import _cdn_paths, _to_url_tree
from plugins.lookup.tls import LookupModule as TlsLookup
from utils.cache.files import PROJECT_ROOT, read_text
from utils.domains.default_primary import default_domain_primary
from utils.networks.reachability import CLEARNET, TOR, network_of
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

filter_loader.add_directory(str(PROJECT_ROOT / "plugins" / "filter"))

APP = "web-app-xwiki"
DESIGN_DIR = PROJECT_ROOT / "roles" / "sys-front-inj-design"
DESIGN_VARS = DESIGN_DIR / ROLE_FILE_VARS_MAIN
HEAD = DESIGN_DIR / "templates" / "head_sub.j2"
XWIKI_DIR = PROJECT_ROOT / "roles" / APP
XWIKI_VARS = XWIKI_DIR / ROLE_FILE_VARS_MAIN
XWIKI_SHEET = XWIKI_DIR / "templates" / "style.css.j2"

DOMAIN = default_domain_primary()
ONION = "a" * 56 + ".onion"
CLEAR_VHOST = f"x.wiki.{DOMAIN}"
ONION_VHOST = f"x.wiki.{ONION}"
CDN_ROOT = "/nonexistent/infinito/cdn"
CDN_BASE = {CLEARNET: f"https://cdn.{DOMAIN}", TOR: f"http://cdn.{ONION}"}
ROLE_SHEET = re.compile(rf'href="([^"]*/roles/{APP}/[^"]*)"')

LEGACY_DST = (
    "{{ [lookup('cdn', application_id).role.release.css, 'style.css'] | path_join }}"
)


class _Stub(LookupBase):
    def __init__(self, answer):
        super().__init__()
        self._answer = answer

    def run(self, terms, variables=None, **kwargs):
        return [self._answer(variables or {}, *terms)]


def _cdn(variables, application_id):
    base = CDN_BASE[network_of(variables["domain"])]
    paths = _cdn_paths(CDN_ROOT, application_id, "latest")
    return {**paths, "urls": _to_url_tree(paths, paths["root"], base)}


def _domains(siblings):
    tree = {APP: siblings, "web-svc-cdn": [f"cdn.{DOMAIN}", f"cdn.{ONION}"]}
    return lambda _variables, *terms: tree[terms[0]] if terms else tree


def _templar(siblings, extra):
    stubs = {
        "domains": _domains(siblings),
        "applications": lambda _variables: {APP: {}},
        "cdn": _cdn,
        "design": lambda _variables, _app: {"bootstrap": False},
        "path_absolute": lambda _variables, *parts: "/".join(parts),
        "local_mtime_qs": lambda _variables, _path: "?version=1",
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

    declared = {
        **DataLoader().load_from_file(str(XWIKI_VARS), trusted_as_template=True),
        **DataLoader().load_from_file(str(DESIGN_VARS), trusted_as_template=True),
    }
    variables = {
        **declared,
        "application_id": APP,
        "TLS_ENABLED": True,
        "TLS_MODE": "letsencrypt",
        **extra,
    }
    return Templar(loader=DataLoader(), variables=variables), mock.patch.object(
        lookup_loader, "get", side_effect=get
    )


def resolve(siblings, domain, expression):
    """Template ``expression`` for one vhost of the role.

    Args:
        siblings: the domains the node serves the role on, canonical first.
        domain: the vhost being rendered.
        expression: a Jinja expression, trusted as a template.

    Returns:
        The rendered value.
    """
    templar, patch = _templar(siblings, {"domain": domain})
    with patch:
        return templar.template(trust_as_template(expression))


def render_xwiki_sheet(siblings, domain):
    """Render XWiki's role stylesheet for one vhost with its real ``XWIKI_URL``.

    Args:
        siblings: the domains the node serves XWiki on.
        domain: the vhost being rendered.

    Returns:
        The rendered stylesheet.
    """
    origin = resolve(siblings, domain, "{{ XWIKI_URL }}")
    environment = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    return environment.from_string(read_text(str(XWIKI_SHEET))).render(
        XWIKI_URL=origin, XWIKI_CORE_VERSION="0.0.0"
    )


def deploy(siblings, dst_expression, file_expression, head_source):
    """Replay the per-vhost design pass of ``sys-front-inj-all``.

    Args:
        siblings: the vhosts in the order the front proxy renders them.
        dst_expression: the expression that names the stylesheet's CDN path.
        file_expression: the expression the ``app_style_file`` fact takes.
        head_source: the ``head_sub.j2`` source that links the stylesheet.

    Returns:
        ``(files, served)``: the CDN files after every vhost wrote its render,
        and per vhost ``(own render, linked path, linked version)``.
    """
    files, renders, links = {}, {}, {}
    for vhost in siblings:
        css = render_xwiki_sheet(siblings, vhost)
        renders[vhost] = css
        files[resolve(siblings, vhost, dst_expression)] = css
        facts = {
            "domain": vhost,
            "app_style_present": True,
            "app_style_css": css,
            "app_style_file": resolve(siblings, vhost, file_expression),
            "design_js_one_liner": "",
        }
        templar, patch = _templar(siblings, facts)
        with patch:
            links[vhost] = ROLE_SHEET.search(
                templar.template(trust_as_template(head_source))
            ).group(1)
    served = {}
    for vhost, href in links.items():
        url = urlsplit(href)
        served[vhost] = (
            renders[vhost],
            CDN_ROOT + url.path,
            parse_qs(url.query)["version"][0],
        )
    return files, served


class TestXwikiSheetFollowsTheVhost(unittest.TestCase):
    def setUp(self) -> None:
        siblings = [CLEAR_VHOST, ONION_VHOST]
        self.clear = render_xwiki_sheet(siblings, CLEAR_VHOST)
        self.onion = render_xwiki_sheet(siblings, ONION_VHOST)

    def test_the_clearnet_render_names_no_onion_host(self) -> None:
        self.assertIn(f"https://{CLEAR_VHOST}/resources/icons/", self.clear)
        self.assertNotIn(".onion", self.clear)

    def test_the_onion_render_names_no_clearnet_host(self) -> None:
        self.assertIn(f"http://{ONION_VHOST}/resources/icons/", self.onion)
        self.assertNotIn(CLEAR_VHOST, self.onion)


class TestOnePathPerNetwork(unittest.TestCase):
    def test_two_networks_write_two_files(self) -> None:
        siblings = [CLEAR_VHOST, ONION_VHOST]
        paths = {resolve(siblings, vhost, "{{ css_app_dst }}") for vhost in siblings}
        self.assertEqual(
            paths,
            {
                f"{CDN_ROOT}/roles/{APP}/latest/css/style.css",
                f"{CDN_ROOT}/roles/{APP}/latest/css/onion-style.css",
            },
        )

    def test_a_single_network_keeps_the_legacy_path(self) -> None:
        for vhost in (CLEAR_VHOST, ONION_VHOST):
            with self.subTest(vhost=vhost):
                self.assertEqual(
                    resolve([vhost], vhost, "{{ css_app_dst }}"),
                    resolve([vhost], vhost, LEGACY_DST),
                )


class TestEachVhostLinksItsOwnRender(unittest.TestCase):
    def setUp(self) -> None:
        self.files, self.served = deploy(
            [CLEAR_VHOST, ONION_VHOST],
            "{{ css_app_dst }}",
            "{{ css_app_file }}",
            read_text(str(HEAD)),
        )

    def test_the_linked_file_holds_the_vhost_render(self) -> None:
        for vhost, (own, path, _version) in self.served.items():
            with self.subTest(vhost=vhost):
                self.assertEqual(self.files[path], own)

    def test_the_clearnet_document_loads_no_onion_host(self) -> None:
        _own, path, _version = self.served[CLEAR_VHOST]
        self.assertNotIn(".onion", self.files[path])

    def test_the_version_busts_the_cache_of_the_linked_file(self) -> None:
        for vhost, (_own, path, version) in self.served.items():
            with self.subTest(vhost=vhost):
                digest = hashlib.sha1(
                    self.files[path].encode(), usedforsecurity=False
                ).hexdigest()
                self.assertEqual(version, digest)


class TestTheSharedPathLeaks(unittest.TestCase):
    """Negative control: the single pre-fix path reproduces the CI leak."""

    def test_the_clearnet_document_loads_the_onion_render(self) -> None:
        head = read_text(str(HEAD)).replace("app_style_file", "'style.css'")
        files, served = deploy(
            [CLEAR_VHOST, ONION_VHOST], LEGACY_DST, "style.css", head
        )
        own, path, _version = served[CLEAR_VHOST]
        self.assertEqual(len(files), 1)
        self.assertNotEqual(files[path], own)
        self.assertIn(f"http://{ONION_VHOST}/resources/icons/", files[path])


if __name__ == "__main__":
    unittest.main()
