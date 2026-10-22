import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

RELEASE_LIB = PROJECT_ROOT / "roles/web-app-moodle/files/build/moodle/release.sh"

ENVIRONMENT_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<COMPATIBILITY_MATRIX>
  <MOODLE version="4.5" requires="4.1.2">
  </MOODLE>
  <MOODLE version="5.3" requires="4.4">
  </MOODLE>
</COMPATIBILITY_MATRIX>
"""

UPGRADE_PATH = "4.5.15 4.1.2\n5.3.0 4.4.0\n"


class TestMoodleRelease(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def call(self, function, *args):
        return subprocess.run(
            ["bash", "-c", f'. "$0"; {function} "$@"', str(RELEASE_LIB), *args],
            capture_output=True,
            text=True,
            check=False,
        )

    def output(self, function, *args):
        done = self.call(function, *args)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def file(self, name, content):
        path = self.root / name
        path.write_text(content)
        return str(path)

    def test_normalize_strips_the_build_suffix(self):
        self.assertEqual(
            self.output("moodle_normalize_release", "4.3.2 (Build: 20231222)"),
            "4.3.2",
        )

    def test_normalize_drops_the_weekly_plus(self):
        self.assertEqual(
            self.output("moodle_normalize_release", "4.5.15+ (Build: 20261021)"),
            "4.5.15",
        )

    def test_normalize_completes_a_dot_zero_release(self):
        self.assertEqual(self.output("moodle_normalize_release", "5.3"), "5.3.0")

    def test_normalize_reads_a_development_release_as_its_branch(self):
        self.assertEqual(self.output("moodle_normalize_release", "5.0dev"), "5.0.0")

    def test_normalize_rejects_an_empty_release(self):
        self.assertNotEqual(self.call("moodle_normalize_release", "").returncode, 0)

    def test_release_of_reads_version_php(self):
        version = self.file(
            "version.php",
            "<?php\n$version  = 2023100902.00;\n"
            "$release  = '4.3.2 (Build: 20231222)'; // Human-friendly version name\n",
        )
        self.assertEqual(self.output("moodle_release_of", version), "4.3.2")

    def test_release_of_fails_without_a_release(self):
        version = self.file("version.php", "<?php\n$version = 1;\n")
        self.assertNotEqual(self.call("moodle_release_of", version).returncode, 0)

    def test_at_least_holds_for_an_equal_release(self):
        self.assertEqual(
            self.call("moodle_release_at_least", "4.4.0", "4.4.0").returncode, 0
        )

    def test_at_least_orders_numerically(self):
        self.assertEqual(
            self.call("moodle_release_at_least", "4.10.0", "4.9.0").returncode, 0
        )

    def test_at_least_fails_for_an_older_release(self):
        self.assertNotEqual(
            self.call("moodle_release_at_least", "4.3.2", "4.4.0").returncode, 0
        )

    def test_requires_reads_the_branch_of_the_release(self):
        xml = self.file("environment.xml", ENVIRONMENT_XML)
        self.assertEqual(self.output("moodle_release_requires", xml, "5.3.0"), "4.4.0")

    def test_requires_reads_the_transit_branch(self):
        xml = self.file("environment.xml", ENVIRONMENT_XML)
        self.assertEqual(
            self.output("moodle_release_requires", xml, "4.5.15"), "4.1.2"
        )

    def test_requires_fails_for_an_unknown_branch(self):
        xml = self.file("environment.xml", ENVIRONMENT_XML)
        self.assertNotEqual(
            self.call("moodle_release_requires", xml, "6.0.0").returncode, 0
        )

    def test_next_release_takes_the_pinned_one_when_it_accepts_the_site(self):
        path = self.file("upgrade-path", UPGRADE_PATH)
        self.assertEqual(self.output("moodle_next_release", "4.5.4", path), "5.3.0")

    def test_next_release_takes_the_transit_below_the_pinned_minimum(self):
        path = self.file("upgrade-path", UPGRADE_PATH)
        self.assertEqual(self.output("moodle_next_release", "4.3.2", path), "4.5.15")

    def test_next_release_skips_a_transit_the_site_already_passed(self):
        path = self.file("upgrade-path", UPGRADE_PATH)
        self.assertEqual(self.output("moodle_next_release", "4.5.20", path), "5.3.0")

    def test_next_release_fails_below_every_minimum_source(self):
        path = self.file("upgrade-path", UPGRADE_PATH)
        self.assertNotEqual(
            self.call("moodle_next_release", "3.11.8", path).returncode, 0
        )

    def test_next_release_fails_on_the_newest_release(self):
        path = self.file("upgrade-path", UPGRADE_PATH)
        self.assertNotEqual(
            self.call("moodle_next_release", "5.3.0", path).returncode, 0
        )


if __name__ == "__main__":
    unittest.main()
