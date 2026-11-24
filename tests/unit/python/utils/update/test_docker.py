from __future__ import annotations

import json
import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.update.docker import (
    _registry_cursor,
    collect_entries,
    sourced_services,
    update_config_versions,
)
from utils.update.docker.tags import fetch_mcr_tags

SOURCED = """bundled:
  image: example/app
  version: v1.0.0
  update:
    type: http_regex
    url: https://example.invalid/bundle
    pattern: "app:(v[0-9.]+)"
tracked:
  image: example/side
  version: v2.0.0
  other_version: v3.0.0
  update:
    - key: other_version
      type: git_tags
      repository: https://example.invalid/side.git
plain:
  image: example/plain
  version: v4.0.0
"""


class TestRegistryCursor(unittest.TestCase):
    def test_v_prefixed_pin_seeds_cursor(self) -> None:
        self.assertEqual(_registry_cursor("v19.1.1"), "v")

    def test_bare_numeric_pin_scans_from_start(self) -> None:
        self.assertIsNone(_registry_cursor("19.1.1"))


class TestDeclaredSource(unittest.TestCase):
    def test_a_version_with_its_own_source_is_left_to_that_source(self) -> None:
        root = Path(tempfile.mkdtemp())
        config = root / "roles" / "web-app-example" / ROLE_FILE_META_SERVICES
        config.parent.mkdir(parents=True)
        config.write_text(SOURCED, encoding="utf-8")

        self.assertEqual(sourced_services(config), {"bundled"})
        self.assertEqual(
            sorted(entry.service for entry in collect_entries(root)),
            ["plain", "tracked"],
        )


class TestUpdateDocker(unittest.TestCase):
    def test_update_config_versions_updates_only_target_services(self) -> None:
        original = """moodle:
  version:            "4.5" # Keep comment
  image:              bitnamilegacy/moodle
nginx:
  version:            alpine
  image:              nginx
"""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "main.yml"
            config_path.write_text(original, encoding="utf-8")

            changed = update_config_versions(config_path, {"moodle": "5.0"})

            self.assertTrue(changed)
            updated = read_text(str(config_path))
            self.assertIn('version:            "5.0" # Keep comment', updated)
            self.assertIn("version:            alpine", updated)
            self.assertNotIn('version:            "4.5" # Keep comment', updated)

    def test_a_bump_drops_the_image_tag_suppression_of_the_old_tag(self) -> None:
        original = """penpot:
  image: penpotapp/exporter
  version: "2.18.5"
  security:
    suppressions:
      # nocheck: cve upstream ships no rebuild yet
      - image_tag: "2.18.5"
        until: 2026-12-31
# nocheck: shared
nginx:
  image: nginx
  version: "1.29"
  security:
    suppressions:
      # nocheck: cve upstream ships no rebuild yet
      - image_tag: "1.29"
        until: 2026-12-31
"""
        expected = original.replace(
            """  version: "2.18.5"
  security:
    suppressions:
      # nocheck: cve upstream ships no rebuild yet
      - image_tag: "2.18.5"
        until: 2026-12-31
""",
            '  version: "2.18.6"\n',
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "main.yml"
            config_path.write_text(original, encoding="utf-8")

            update_config_versions(config_path, {"penpot": "2.18.6"})

            self.assertEqual(read_text(str(config_path)), expected)


_MCR_TAGS = "https://mcr.microsoft.com/v2/foo/bar/tags/list?n=100"
_MCR_NEXT = "https://mcr.microsoft.com/v2/foo/bar/tags/list?last=a"


class TestMcrPaging(unittest.TestCase):
    def _page(self, link: str) -> tuple[list[str], list[str]]:
        pages = []
        for found, header in ((["a"], f'<{link}>; rel="next"'), (["b"], "")):
            page = mock.MagicMock()
            page.__enter__.return_value = page
            page.read.return_value = json.dumps({"tags": found}).encode()
            page.headers = {"Link": header}
            pages.append(page)
        with mock.patch("urllib.request.urlopen", side_effect=pages) as opened:
            tags = fetch_mcr_tags("mcr.microsoft.com/foo/bar")
        return tags, [call.args[0].full_url for call in opened.call_args_list]

    def test_a_link_next_on_the_registry_pages(self) -> None:
        for link in ("/v2/foo/bar/tags/list?last=a", _MCR_NEXT):
            with self.subTest(link=link):
                self.assertEqual(self._page(link), (["a", "b"], [_MCR_TAGS, _MCR_NEXT]))

    def test_a_link_next_off_the_registry_stops_paging(self) -> None:
        for link in (
            "https://evil.example/v2/foo/bar/tags/list?last=a",
            "http://mcr.microsoft.com/v2/foo/bar/tags/list?last=a",
            "//evil.example/v2/foo/bar/tags/list?last=a",
        ):
            with self.subTest(link=link):
                self.assertEqual(self._page(link), (["a"], [_MCR_TAGS]))


if __name__ == "__main__":
    unittest.main()
