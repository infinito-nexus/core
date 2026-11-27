from __future__ import annotations

import unittest
from html.parser import HTMLParser
from urllib.parse import urlsplit

from plugins.filter.csp_filters import FilterModule
from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_CSP

APPLICATION_ID = "web-app-agent-fixture"
ROLE = PROJECT_ROOT / "roles" / APPLICATION_ID
INDEX = ROLE / "files" / "app" / "html" / "index.html"
DOMAINS = {
    APPLICATION_ID: ["agent-fixture.example.org"],
    "web-svc-cdn": ["cdn.example.org"],
}
GSTATIC = "https://fonts.gstatic.com"


class _Stylesheets(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.origins: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        values = dict(attrs)
        if tag != "link" or values.get("rel") != "stylesheet":
            return
        parts = urlsplit(values.get("href") or "")
        if parts.netloc:
            self.origins.append(f"{parts.scheme}://{parts.netloc}")


def _external_stylesheet_origins() -> list[str]:
    parser = _Stylesheets()
    parser.feed(read_text(str(INDEX)))
    return parser.origins


def _tokens(csp: dict, directive: str) -> list[str]:
    applications = {APPLICATION_ID: {"csp": csp, "services": {}}}
    header = FilterModule().build_csp_header(
        applications, APPLICATION_ID, DOMAINS, "https"
    )
    for raw in header.split(";"):
        name, _, tokens = raw.strip().partition(" ")
        if name == directive:
            return tokens.split()
    raise AssertionError(f"no {directive} in {header!r}")


def _role_csp() -> dict:
    return load_yaml_str(read_text(str(ROLE / ROLE_FILE_META_CSP)))


class TestAgentFixtureCsp(unittest.TestCase):
    def test_csp_admits_every_seeded_stylesheet_and_its_fonts(self) -> None:
        origins = _external_stylesheet_origins()
        self.assertTrue(
            origins,
            "the fixture's seeded third-party web font is gone from index.html; "
            "drop its CSP whitelist with it",
        )
        style_elem = _tokens(_role_csp(), "style-src-elem")
        for origin in origins:
            with self.subTest(origin=origin):
                self.assertIn(
                    origin,
                    style_elem,
                    "hlth-csp fails the fixture's vhosts when the browser "
                    "blocks the seeded stylesheet",
                )
        self.assertIn(GSTATIC, _tokens(_role_csp(), "font-src"))

    def test_default_csp_blocks_the_seeded_stylesheet(self) -> None:
        style_elem = _tokens({}, "style-src-elem")
        for origin in _external_stylesheet_origins():
            with self.subTest(origin=origin):
                self.assertNotIn(origin, style_elem)
        self.assertNotIn(GSTATIC, _tokens({}, "font-src"))


if __name__ == "__main__":
    unittest.main()
