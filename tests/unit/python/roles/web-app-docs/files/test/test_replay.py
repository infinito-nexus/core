from __future__ import annotations

import re
import unittest

import jinja2

from utils.cache.files import read_text

from . import PROJECT_ROOT
from .test_mirror import CONTEXT, PRODUCTION, TEMPLATE_DIR, TEMPLATE_NAME

REPLAY = PROJECT_ROOT / "roles" / "web-app-docs" / "files" / "test" / "replay.sh"
PLACEHOLDER = re.compile(r"<your-[a-z-]+>")
FILLED = re.compile(r"s#(<your-[a-z-]+>)#")
SERVER = "<your-server>"


def _published(*, is_host: bool) -> set[str]:
    environment = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        keep_trailing_newline=True,
        autoescape=jinja2.select_autoescape(),
    )
    rendered = environment.get_template(TEMPLATE_NAME).render(
        {
            **CONTEXT,
            "application_is_host": is_host,
            "application_needs_clearnet_resolver": True,
            "application_needs_service_provider_country": True,
        }
    )
    found = PRODUCTION.search(rendered)
    assert found, "the template publishes no Production block"
    return set(PLACEHOLDER.findall(found.group(1)))


class TestReplayFillsEveryPlaceholder(unittest.TestCase):
    def test_both_shapes_leave_nothing_for_the_guard(self) -> None:
        filled = set(FILLED.findall(read_text(str(REPLAY))))
        for is_host in (False, True):
            with self.subTest(is_host=is_host):
                published = _published(is_host=is_host) - {SERVER}
                self.assertEqual(published - filled, set())

    def test_the_recipe_names_its_server_through_host(self) -> None:
        self.assertIn(SERVER, _published(is_host=False))
        self.assertIn("s#^HOST=.*#HOST=", read_text(str(REPLAY)))


if __name__ == "__main__":
    unittest.main()
