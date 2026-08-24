import re
import shutil
import tempfile
import unittest
from pathlib import Path

from cli.administration.inventory.credentials.reset.cli import (
    _backup,
    _mirror_host_vars,
    _parse_app_variants,
)

STAMPED = re.compile(r"^localhost\.yml\.\d{8}T\d{6}Z\.backup$")


class TestBackup(unittest.TestCase):
    def setUp(self):
        self.workdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.workdir, ignore_errors=True)
        self.host_vars_file = self.workdir / "localhost.yml"
        self.host_vars_file.write_text("TLS_ENABLED: true\n", encoding="utf-8")

    def test_the_copy_carries_a_utc_stamp(self):
        self.assertRegex(_backup(self.host_vars_file).name, STAMPED)

    def test_the_copy_holds_the_pre_rotation_content(self):
        copy = _backup(self.host_vars_file)
        self.host_vars_file.write_text("TLS_ENABLED: false\n", encoding="utf-8")
        content = copy.read_text(encoding="utf-8")  # nocheck: cache-read
        self.assertEqual(content, "TLS_ENABLED: true\n")

    def test_the_original_survives(self):
        _backup(self.host_vars_file)
        self.assertTrue(self.host_vars_file.exists())


class TestMirrorHostVars(unittest.TestCase):
    def setUp(self):
        self.host_vars_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.host_vars_dir, ignore_errors=True)
        self.source = self.host_vars_dir / "mgr-01.yml"
        self.source.write_text("rotated: true\n", encoding="utf-8")
        for host in ("wrk-01", "nfs-server"):
            (self.host_vars_dir / f"{host}.yml").write_text(
                "rotated: false\n", encoding="utf-8"
            )

    def test_every_other_host_gets_the_rotated_file(self):
        mirrored = _mirror_host_vars(self.host_vars_dir, self.source)
        self.assertEqual(mirrored, ["nfs-server", "wrk-01"])
        for host in mirrored:
            path = self.host_vars_dir / f"{host}.yml"
            self.assertEqual(
                path.read_text(encoding="utf-8"),  # nocheck: cache-read
                "rotated: true\n",
            )

    def test_a_backup_is_not_mirrored_over(self):
        backup = _backup(self.source)
        _mirror_host_vars(self.host_vars_dir, self.source)
        content = backup.read_text(encoding="utf-8")  # nocheck: cache-read
        self.assertEqual(content, "rotated: true\n")
        self.assertNotIn(
            backup.stem, _mirror_host_vars(self.host_vars_dir, self.source)
        )


class TestParseAppVariants(unittest.TestCase):
    def test_an_absent_value_is_empty(self):
        self.assertEqual(_parse_app_variants(None), {})

    def test_indices_become_integers(self):
        self.assertEqual(_parse_app_variants('{"web-app-a": "2"}'), {"web-app-a": 2})

    def test_broken_json_aborts(self):
        with self.assertRaises(SystemExit):
            _parse_app_variants("{")

    def test_a_non_integer_index_aborts(self):
        with self.assertRaises(SystemExit):
            _parse_app_variants('{"web-app-a": "base"}')


if __name__ == "__main__":
    unittest.main()
