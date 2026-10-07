import os
import pwd
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

ENTRYPOINT = PROJECT_ROOT / "roles/web-app-moodle/files/build/moodle-entrypoint.sh"

FPM_STUB = "#!/usr/bin/env bash\nexit 0\n"

LAYOUT_4 = {"version.php": "4.5.11", "auth/oidc/version.php": "4.5.8"}
LAYOUT_5 = {"public/version.php": "5.3.0", "public/auth/oidc/version.php": "5.2.1"}


class TestMoodleEntrypoint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "source"
        self.code = self.root / "code"
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "php-fpm"
        stub.write_text(FPM_STUB)
        stub.chmod(0o755)
        self.env = dict(os.environ)
        self.env.update(
            PATH=f"{bin_dir}{os.pathsep}{self.env['PATH']}",
            MOODLE_CODE_DIR=str(self.code),
            MOODLE_DATA_DIR=str(self.root / "data"),
            MOODLE_LOCAL_CACHE_DIR=str(self.root / "localcache"),
            MOODLE_SOURCE_DIR=str(self.source),
            MOODLE_RUNTIME_USER=pwd.getpwuid(os.getuid()).pw_name,
            MOODLE_VERSION_FILE="public/version.php",
        )

    def write(self, tree, files):
        for name, content in files.items():
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def ship(self, files):
        shutil.rmtree(self.source, ignore_errors=True)
        self.write(self.source, files)

    def run_entrypoint(self, release):
        return subprocess.run(
            ["bash", str(ENTRYPOINT), "php-fpm"],
            env={**self.env, "MOODLE_RELEASE": release},
            capture_output=True,
            text=True,
            check=False,
        )

    def start(self, release):
        done = self.run_entrypoint(release)
        self.assertEqual(done.returncode, 0, done.stderr)

    def shipped_files_in_the_volume(self):
        return {
            name for name in {*LAYOUT_4, *LAYOUT_5} if (self.code / name).is_file()
        }

    def test_the_first_start_fills_the_code_volume(self):
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        self.assertEqual(self.shipped_files_in_the_volume(), set(LAYOUT_5))

    def test_a_restart_on_the_same_release_keeps_what_the_volume_holds(self):
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        added = {"public/local/extra/version.php": "added after the bootstrap"}
        self.write(self.code, added)
        self.start("5.3.0")
        self.assertTrue((self.code / "public/local/extra/version.php").is_file())

    def test_another_release_replaces_the_tree_and_drops_what_it_no_longer_ships(self):
        self.ship(LAYOUT_4)
        self.start("4.5.11")
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        self.assertEqual(self.shipped_files_in_the_volume(), set(LAYOUT_5))

    def test_a_volume_the_previous_entrypoint_marked_done_is_replaced(self):
        self.write(self.code, LAYOUT_4)
        (self.code / ".bootstrap.done").touch()
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        self.assertEqual(self.shipped_files_in_the_volume(), set(LAYOUT_5))

    def test_a_missing_source_tree_fails_and_leaves_the_volume_unmarked(self):
        done = self.run_entrypoint("5.3.0")
        self.assertNotEqual(done.returncode, 0)
        self.assertFalse((self.code / ".bootstrap.done").exists())

    def test_a_failed_copy_keeps_the_tree_the_volume_held(self):
        self.ship(LAYOUT_4)
        self.start("4.5.11")
        shutil.rmtree(self.source)
        done = self.run_entrypoint("5.3.0")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.shipped_files_in_the_volume(), set(LAYOUT_4))
        self.assertEqual(read_text(str(self.code / ".bootstrap.done")), "4.5.11")

    def test_an_image_older_than_the_recorded_release_refuses_to_replace_it(self):
        self.ship(LAYOUT_5)
        self.start("5.10.0")
        self.ship(LAYOUT_4)
        done = self.run_entrypoint("5.9.2")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("5.10.0", done.stderr)
        self.assertEqual(self.shipped_files_in_the_volume(), set(LAYOUT_5))
        self.assertEqual(read_text(str(self.code / ".bootstrap.done")), "5.10.0")


if __name__ == "__main__":
    unittest.main()
