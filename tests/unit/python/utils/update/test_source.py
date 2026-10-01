from __future__ import annotations

import tempfile
import unittest
import unittest.mock as mock
from pathlib import Path

from utils.roles.mapping import ROLE_FILE_META_SERVICES
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


def _repo(services: str = SERVICES) -> Path:
    tmp = Path(tempfile.mkdtemp())
    config = tmp / "roles" / "web-app-example" / ROLE_FILE_META_SERVICES
    config.parent.mkdir(parents=True)
    config.write_text(services, encoding="utf-8")
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


if __name__ == "__main__":
    unittest.main()
