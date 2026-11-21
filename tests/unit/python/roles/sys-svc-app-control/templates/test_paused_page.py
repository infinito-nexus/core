"""The paused page shows the sleeping beaver, the paused notice and every
contact channel, and every word on it comes from the catalogue entry or the
contact data."""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "sys-svc-app-control"
TEMPLATE = ROLE / "templates" / "paused.html.j2"
STYLE = ROLE / "files" / "paused.css"
SOURCE = load_yaml(ROLE / "files" / "paused_i18n.yml")
BRANDS = load_yaml(ROLE / ROLE_FILE_VARS_MAIN)["APP_CONTROL_CONTACT_BRANDS"]

TEXTS = {key: f"{key} from the catalogue" for key in SOURCE} | {"dir": "rtl"}
CONTACT = {
    "email": "ops@example.org",
    "phone": "+49 30 1234 567",
    "newsletter": "https://news.example.org/subscribe",
    "mastodon": "@ops@social.example.org",
    "web-app-bluesky": "",
    "matrix": "   ",
    "telegram": "https://t.me/ops",
    "signal": " ops.42 ",
}
LISTED = {
    channel: address.strip() for channel, address in CONTACT.items() if address.strip()
}
LABELS = {
    "email": TEXTS["channel_email"],
    "phone": TEXTS["channel_phone"],
    "newsletter": TEXTS["channel_newsletter"],
    "mastodon": BRANDS["mastodon"],
    "telegram": "telegram",
    "signal": "signal",
}


class _Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: list[str] = []
        self.texts: list[tuple[str, str]] = []
        self.links: list[str] = []
        self.classes: set[str] = set()
        self.root: dict[str, str] = {}
        self.style = ""

    def handle_starttag(self, tag, attrs):
        attributes = {name: value or "" for name, value in attrs}
        if tag == "html":
            self.root = attributes
        if tag == "a":
            self.links.append(attributes["href"])
        self.classes.update(attributes.get("class", "").split())
        self.stack.append(tag)

    def handle_endtag(self, tag):
        while self.stack and self.stack.pop() != tag:
            continue

    def handle_data(self, data):
        if "style" in self.stack:
            self.style += data
            return
        text = data.strip()
        if text:
            self.texts.append((self.stack[-1], text))

    def text_of(self, tag: str) -> list[str]:
        return [text for owner, text in self.texts if owner == tag]


def _render(source: str) -> _Page:
    env = Environment(
        trim_blocks=True,
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["combine"] = lambda base, other: {**base, **other}
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    rendered = env.from_string(source).render(
        paused_entry={"key": "de", "value": TEXTS},
        APP_CONTROL_CONTACT_BRANDS=BRANDS,
        APP_CONTROL_PAUSED_STYLE=read_text(str(STYLE)),
        service_provider={"contact": CONTACT},
    )
    page = _Page()
    page.feed(rendered)
    page.close()
    return page


def _foreign_texts(page: _Page) -> list[str]:
    allowed = (
        {value for key, value in TEXTS.items() if key != "dir"}
        | set(LISTED.values())
        | set(LABELS.values())
    )
    return [text for _, text in page.texts if text not in allowed]


def _template() -> str:
    return read_text(str(TEMPLATE))


class TestPausedPage(unittest.TestCase):
    def setUp(self) -> None:
        self.page = _render(_template())

    def test_the_page_carries_the_language_and_direction_of_its_entry(self) -> None:
        self.assertEqual(self.page.root, {"lang": "de", "dir": "rtl"})

    def test_the_scene_is_the_beaver_sleeping_behind_the_pause_sign(self) -> None:
        self.assertLessEqual(
            {"scene", "beaver", "z", "z1", "z2", "z3"}, self.page.classes
        )
        self.assertEqual(
            [text for owner, text in self.page.texts if owner == "title"],
            [TEXTS["title"], TEXTS["illustration"]],
        )

    def test_the_beaver_and_its_sleep_marks_are_animated(self) -> None:
        for selector in (".beaver", ".z"):
            with self.subTest(selector=selector):
                self.assertRegex(
                    self.page.style,
                    rf"(?m)^{re.escape(selector)}\{{[^}}]*animation:(?!none)\w+",
                )

    def test_the_page_states_that_the_service_is_paused(self) -> None:
        self.assertEqual(self.page.text_of("h1"), [TEXTS["heading"]])
        self.assertEqual(self.page.text_of("p"), [TEXTS["notice"]])
        self.assertEqual(self.page.text_of("h2"), [TEXTS["contact"]])

    def test_every_declared_contact_channel_is_listed_with_its_label(self) -> None:
        self.assertEqual(
            self.page.text_of("dt"), [LABELS[channel] for channel in LISTED]
        )
        addresses = self.page.text_of("dd") + self.page.text_of("a")
        self.assertEqual(sorted(addresses), sorted(LISTED.values()))

    def test_mail_phone_and_web_channels_are_links(self) -> None:
        self.assertEqual(
            self.page.links,
            [
                "mailto:ops@example.org",
                "tel:+49301234567",
                "https://news.example.org/subscribe",
                "https://t.me/ops",
            ],
        )

    def test_every_word_comes_from_the_catalogue_entry_or_the_contact_data(
        self,
    ) -> None:
        self.assertEqual(_foreign_texts(self.page), [])

    def test_the_page_reads_exactly_the_messages_of_the_catalogue_source(
        self,
    ) -> None:
        read = set(re.findall(r"\btexts\.(\w+)", _template())) - {"dir"}
        self.assertEqual(read, set(SOURCE))

    def test_negative_control_a_literal_text_in_the_template_is_reported(
        self,
    ) -> None:
        drifted = _template().replace("<h2>", "<h2>Contact us: ")
        self.assertNotEqual(drifted, _template())
        self.assertTrue(_foreign_texts(_render(drifted)))

    def test_negative_control_a_skipped_channel_breaks_the_listing(self) -> None:
        drifted = _template().replace(
            "if raw | trim %}", "if raw | trim and channel != 'phone' %}"
        )
        self.assertNotEqual(drifted, _template())
        self.assertNotIn(LABELS["phone"], _render(drifted).text_of("dt"))


if __name__ == "__main__":
    unittest.main()
