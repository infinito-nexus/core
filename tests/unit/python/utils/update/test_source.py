from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.roles.mapping import ROLE_DIR_META_ADDONS, ROLE_FILE_META_SERVICES
from utils.update import source as module

SERVICES = """\
---
app:
  image: example
  version: "1.2.3"
  app_version: 2.0.0
  update:
    - key: app_version
      type: git_tags
      repository: https://example.test/app.git
      match: "v"
      strip: true
    - key: version
      type: npm
      package: example
frozen:
  # nocheck: version-source  Reason: stays where it is
  app_version: 1.0.0
  update:
    key: app_version
    type: npm
    package: frozen
"""


ADDONS = {
    "released": """\
---
enabled: true
version: "v1.2.0"
update:
  monitored: true
  catalog: github-releases
  upstream_id: example/released
config:
  archive: "https://example.test/released/download/v1.2.0/app.tar.gz"
""",
    "declared": """\
---
enabled: true
version: "3.4"
update:
  type: http_regex
  url: https://example.test/metadata.xml
  pattern: '<version>([0-9.]+)</version>'
""",
    "unmonitored": """\
---
enabled: true
version: "1.0.0"
update:
  monitored: false
  catalog: github-releases
  upstream_id: example/unmonitored
""",
    "catalogued": """\
---
enabled: true
version: "1.0.0"
update:
  monitored: true
  catalog: wordpress-org
""",
    "frozen": """\
---
enabled: true
# nocheck: unwatched-version  Reason: bound to a checksum
version: "2.0.0"
update:
  monitored: true
  catalog: github-releases
  upstream_id: example/frozen
""",
}


COMPOUND = """\
---
bundle:
  image: example/part
  version: "v1.10.12-v3.0.23"
  update:
    type: http_regex
    url: https://example.test/tags
    pattern: 'core (?P<core>v[0-9.]+)\\npart (?P<part>v[0-9.]+)'
    template: "{part}-{core}"
"""

SUFFIXED = """\
---
bundle:
  image: example/part
  version: "v1.10.12-v3.0.23"
  update:
    type: http_regex
    url: https://example.test/tags
    pattern: 'part (v[0-9.]+-v[0-9.]+)'
"""


def _repo(services: str = SERVICES) -> Path:
    tmp = Path(tempfile.mkdtemp())
    config = tmp / "roles" / "web-app-example" / ROLE_FILE_META_SERVICES
    config.parent.mkdir(parents=True)
    config.write_text(services, encoding="utf-8")
    return tmp


def _addon_repo(addons: dict[str, str] | None = None) -> Path:
    tmp = Path(tempfile.mkdtemp())
    directory = tmp / "roles" / "web-app-example" / ROLE_DIR_META_ADDONS
    directory.mkdir(parents=True)
    for addon_id, content in (ADDONS if addons is None else addons).items():
        (directory / f"{addon_id}.yml").write_text(content, encoding="utf-8")
    return tmp


class TestCollectEntries(unittest.TestCase):
    def test_each_declared_pin_is_collected_and_a_suppressed_one_is_not(self) -> None:
        entries = module.collect_entries(_repo())

        self.assertEqual(
            [(e.entity, e.key, e.current, e.source["type"]) for e in entries],
            [
                ("app", "app_version", "2.0.0", "git_tags"),
                ("app", "version", "1.2.3", "npm"),
            ],
        )
        self.assertEqual([e.line for e in entries], [5, 4])


class TestCandidates(unittest.TestCase):
    def test_match_selects_a_flavour_and_strip_drops_its_prefix(self) -> None:
        root = _repo()
        entry = next(e for e in module.collect_entries(root) if e.key == "app_version")

        with mock.patch.object(
            module, "git_ls_remote_tags", return_value=["v2.1.0", "2.0.5", "nightly"]
        ):
            self.assertEqual(module.candidates(entry, root), ["2.1.0"])


class TestOutdated(unittest.TestCase):
    def _entry(self, root: Path):
        return next(e for e in module.collect_entries(root) if e.key == "app_version")

    def test_a_newer_version_is_reported_and_written_to_its_own_line(self) -> None:
        root = _repo()
        entry = self._entry(root)

        with mock.patch.object(module, "candidates", return_value=["2.1.0"]):
            updates = module.outdated([entry], root)
        self.assertEqual(
            [(u.entry.key, u.latest) for u in updates], [("app_version", "2.1.0")]
        )

        module.apply_updates(updates)
        config = root / "roles" / "web-app-example" / ROLE_FILE_META_SERVICES
        written = config.read_text()  # nocheck: cache-read  just rewritten here
        self.assertIn("app_version: 2.1.0", written)
        self.assertIn('version: "1.2.3"', written)

    def test_an_unchanged_upstream_reports_nothing(self) -> None:
        root = _repo()
        with mock.patch.object(module, "candidates", return_value=["2.0.0", "1.9.9"]):
            self.assertEqual(module.outdated([self._entry(root)], root), [])


class TestTemplate(unittest.TestCase):
    def _outdated(self, services: str, upstream: str) -> list[str]:
        root = _repo(services)
        with mock.patch.object(module, "documents", return_value=upstream):
            updates = module.outdated(module.collect_entries(root), root)
        return [update.latest for update in updates]

    def test_a_template_assembles_the_tag_from_several_upstream_values(self) -> None:
        self.assertEqual(
            self._outdated(COMPOUND, "core v3.0.39\npart v1.11.3\n"),
            ["v1.11.3-v3.0.39"],
        )

    def test_a_templated_tag_moves_when_only_its_suffix_changed(self) -> None:
        self.assertEqual(
            self._outdated(COMPOUND, "core v3.0.39\npart v1.10.12\n"),
            ["v1.10.12-v3.0.39"],
        )

    def test_an_unchanged_or_older_templated_tag_reports_nothing(self) -> None:
        self.assertEqual(self._outdated(COMPOUND, "core v3.0.23\npart v1.10.12\n"), [])
        self.assertEqual(self._outdated(COMPOUND, "core v3.0.23\npart v1.9.0\n"), [])

    def test_without_a_template_a_changed_suffix_is_another_flavour(self) -> None:
        self.assertEqual(self._outdated(SUFFIXED, "part v1.11.3-v3.0.39\n"), [])
        self.assertEqual(
            self._outdated(SUFFIXED, "part v1.11.3-v3.0.23\n"), ["v1.11.3-v3.0.23"]
        )


class TestAddons(unittest.TestCase):
    def test_only_a_declared_or_github_released_addon_pin_is_collected(self) -> None:
        entries = module.collect_entries(_addon_repo())

        self.assertEqual(
            [
                (e.entity, e.key, e.current, e.source["type"], e.line, e.addon)
                for e in entries
            ],
            [
                ("declared", "version", "3.4", "http_regex", 3, True),
                ("released", "version", "v1.2.0", "git_tags", 3, True),
            ],
        )
        self.assertEqual(
            entries[1].source["repository"], "https://github.com/example/released.git"
        )

    def test_an_addon_pin_moves_together_with_the_archive_that_carries_it(self) -> None:
        root = _addon_repo({"released": ADDONS["released"]})
        with mock.patch.object(module, "candidates", return_value=["v1.3.0"]):
            updates = module.find_outdated_updates(root)
        module.apply_updates(updates)

        addon = (
            root / "roles" / "web-app-example" / ROLE_DIR_META_ADDONS / "released.yml"
        )
        written = addon.read_text()  # nocheck: cache-read  just rewritten here
        self.assertIn('version: "v1.3.0"', written)
        self.assertIn("released/download/v1.3.0/app.tar.gz", written)
        self.assertIn("upstream_id: example/released", written)

    def test_an_archive_that_does_not_carry_the_pin_is_reported(self) -> None:
        drifted = ADDONS["released"].replace('version: "v1.2.0"', 'version: "v1.1.0"')
        root = _addon_repo({"drifted": drifted})

        self.assertEqual(
            module.invalid_declarations(root),
            [
                (
                    "web-app-example/addons/drifted.version: config.archive does "
                    "not carry the pinned version, so a bump would move only one "
                    "of the two"
                ),
            ],
        )

    def test_an_addon_block_that_cannot_resolve_is_reported(self) -> None:
        root = _addon_repo(
            {"broken": "---\nenabled: true\nupdate:\n  type: carrier_pigeon\n"}
        )

        self.assertEqual(
            module.invalid_declarations(root),
            [
                (
                    "web-app-example/addons/broken: update.key 'version' names no "
                    "key of the addon"
                ),
                (
                    "web-app-example/addons/broken.version: unknown update.type "
                    "'carrier_pigeon', expected one of git_tags, registry_tags, npm, "
                    "http_regex, script"
                ),
            ],
        )


class TestSemverPins(unittest.TestCase):
    def test_an_update_block_on_a_moving_tag_is_reported(self) -> None:
        root = _repo(SERVICES.replace("app_version: 2.0.0", "app_version: latest"))

        self.assertEqual(
            module.invalid_declarations(root),
            [
                (
                    "web-app-example/app.app_version: 'latest' is not a semver, so "
                    "no upstream version orders above it and the pin never moves"
                ),
            ],
        )

    def test_a_monitored_addon_on_a_moving_tag_is_reported(self) -> None:
        root = _addon_repo(
            {
                "moving": ADDONS["catalogued"].replace('"1.0.0"', '"master"'),
                "pinned": ADDONS["catalogued"],
                "unpinned": ADDONS["catalogued"].replace('version: "1.0.0"\n', ""),
                "unmonitored": ADDONS["unmonitored"].replace('"1.0.0"', '"master"'),
            }
        )

        self.assertEqual(
            module.invalid_declarations(root),
            [
                (
                    "web-app-example/addons/moving.version: 'master' is not a "
                    "semver, so no upstream version orders above it and the pin "
                    "never moves"
                ),
            ],
        )


if __name__ == "__main__":
    unittest.main()
