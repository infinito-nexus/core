"""The design config survives the trip through an HTML attribute.

``sys-front-inj-design`` renders ``templates/js/design-config.json.j2`` and
puts it into ``data-design`` on the injected script tag, HTML-escaped. The
script reads it back with ``JSON.parse``. Three transformations sit between
the value and the browser - ``to_json``, Jinja's ``escape`` and the parser's
entity decoding - and a branding title is operator text, so it can carry a
quote, an angle bracket or an emoji.

If any of those steps disagrees, the parse throws on the first statement of
the inline script and every branded element on the page stays unbranded. The
deploy stays green and the CSP hash still matches, so nothing else reports it.
"""

from __future__ import annotations

import json
import unittest
from html.parser import HTMLParser

from jinja2 import Environment, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text

TEMPLATE = (
    PROJECT_ROOT
    / "roles"
    / "sys-front-inj-design"
    / "templates"
    / "js"
    / "design-config.json.j2"
)
HOSTILE = (
    'Kevin\'s "Nexus" <b>&</b> Co',
    "</script><img src=x onerror=alert(1)>",
    "Zeilen\numbruch\tund Tab",
    "Ümläute und 😀",
)


class _Attribute(HTMLParser):
    """Collect the decoded ``data-design`` of the first tag that carries one."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.value: str | None = None

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name == "data-design" and self.value is None:
                self.value = value


def _render(title, logo, urls):
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    environment.filters["to_json"] = json.dumps
    body = read_text(str(TEMPLATE)).split("%}\n", 1)[1]
    design = {"title": title, "logo": logo, "urls": urls, "slots": {}}
    return environment.from_string(body).render(design=design)


def _through_attribute(rendered: str) -> dict:
    environment = Environment(autoescape=select_autoescape(default_for_string=False))
    tag = environment.from_string(
        '<script data-design="{{ value | e }}"></script>'
    ).render(value=rendered.strip())
    parser = _Attribute()
    parser.feed(tag)
    return json.loads(parser.value)


class TestDesignConfigAttribute(unittest.TestCase):
    def test_a_hostile_title_survives_the_attribute(self) -> None:
        for title in HOSTILE:
            with self.subTest(title=title):
                config = _through_attribute(_render(title, "/srv/logo.png", {}))
                self.assertEqual(config["title"], title)

    def test_a_url_with_an_ampersand_survives(self) -> None:
        urls = {"favicon_ico": "https://cdn.example/f.ico?v=1&x=2"}
        config = _through_attribute(_render("T", "/srv/logo.png", urls))
        self.assertEqual(config["urls"], urls)

    def test_the_urls_are_withheld_while_no_logo_is_configured(self) -> None:
        urls = {"favicon_ico": "https://cdn.example/f.ico"}
        config = _through_attribute(_render("T", False, urls))
        self.assertEqual(config["urls"], {})
        self.assertFalse(config["logo"])

    def test_a_disabled_title_reaches_the_script_as_null(self) -> None:
        config = _through_attribute(_render(False, "/srv/logo.png", {}))
        self.assertIsNone(config["title"])


if __name__ == "__main__":
    unittest.main()
