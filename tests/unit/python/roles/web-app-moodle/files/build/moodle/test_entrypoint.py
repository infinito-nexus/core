import io
import os
import pwd
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT
from utils.cache.files import read_text

BUILD = PROJECT_ROOT / "roles/web-app-moodle/files/build/moodle"
ENTRYPOINT = BUILD / "entrypoint.sh"
RELEASE_LIB = BUILD / "release.sh"

FPM_STUB = "#!/usr/bin/env bash\nexit 0\n"
GOSU_STUB = '#!/usr/bin/env bash\nshift\nexec "$@"\n'
PHP_STUB = """#!/usr/bin/env bash
release="$(sed -n "s/^\\$release *= *'\\([^ ']*\\).*/\\1/p" \
  "${MOODLE_CODE_DIR}/version.php" "${MOODLE_CODE_DIR}/public/version.php" 2>/dev/null | head -n 1)"
printf '%s|%s\\n' "${release}" "$*" >> "${STUB_PHP_LOG}"
case " $* " in
  *" --is-pending "*) exit "${STUB_PENDING_RC}" ;;
esac
exit "${STUB_UPGRADE_RC}"
"""

CP_STUB = (
    "#!/usr/bin/env bash\n"
    'printf %s "$SIBLING_RELEASE" > "${MOODLE_BOOTSTRAP_SENTINEL}"\n'
    'exec @REAL_CP@ "$@"\n'
)

UPGRADE_PATH = "4.5.15 4.1.2\n5.3.0 4.4.0\n"
BITNAMI_CONFIG = "<?php\n$CFG->dataroot  = '/bitnami/moodledata';\n"
ROLE_CONFIG = "<?php\nrequire_once(__DIR__ . '/lib/setup.php');\n"


def version_php(release):
    return f"<?php\n$release  = '{release} (Build: 20261005)';\n"


def flat_tree(release):
    return {"version.php": version_php(release), "auth/oidc/version.php": "plugin"}


LAYOUT_4 = flat_tree("4.5.11")
LAYOUT_5 = {
    "public/version.php": version_php("5.3"),
    "public/auth/oidc/version.php": "plugin",
    "config.php": ROLE_CONFIG,
}


class TestMoodleEntrypoint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.source = self.root / "source"
        self.code = self.root / "code"
        self.transit = self.root / "transit"
        self.transit.mkdir()
        self.php_log = self.root / "php.log"
        self.php_log.touch()
        self.upgrade_path = self.root / "upgrade-path"
        self.upgrade_path.write_text(UPGRADE_PATH)
        self.pack_transit("4.5.15")
        self.stage = self.code / ".bootstrap.stage"
        self.sentinel = self.code / ".bootstrap.done"
        self.real_cp = shutil.which("cp")
        bin_dir = self.bin_dir = self.root / "bin"
        bin_dir.mkdir()
        stubs = {"php-fpm": FPM_STUB, "php": PHP_STUB, "gosu": GOSU_STUB}
        for name, body in stubs.items():
            stub = bin_dir / name
            stub.write_text(body)
            stub.chmod(0o755)
        self.env = dict(os.environ)
        self.env.update(
            PATH=f"{bin_dir}{os.pathsep}{self.env['PATH']}",
            MOODLE_CODE_DIR=str(self.code),
            MOODLE_DATA_DIR=str(self.root / "data"),
            MOODLE_LOCAL_CACHE_DIR=str(self.root / "localcache"),
            MOODLE_SOURCE_DIR=str(self.source),
            MOODLE_BOOTSTRAP_STAGE=str(self.stage),
            MOODLE_BOOTSTRAP_SENTINEL=str(self.sentinel),
            MOODLE_RUNTIME_USER=pwd.getpwuid(os.getuid()).pw_name,
            MOODLE_VERSION_FILE="public/version.php",
            MOODLE_RELEASE_LIB=str(RELEASE_LIB),
            MOODLE_TRANSIT_DIR=str(self.transit),
            MOODLE_UPGRADE_PATH=str(self.upgrade_path),
            MOODLE_CLI_RELPATH="admin/cli",
            STUB_PHP_LOG=str(self.php_log),
            STUB_PENDING_RC="2",
            STUB_UPGRADE_RC="0",
        )

    def sibling_finishes_during_the_copy(self, release):
        """Stub ``cp`` so another container marks the volume done mid-bootstrap.

        Args:
            release: release the sibling records in the bootstrap sentinel.
        """
        stub = self.bin_dir / "cp"
        stub.write_text(CP_STUB.replace("@REAL_CP@", self.real_cp))
        stub.chmod(0o755)
        self.env["SIBLING_RELEASE"] = release

    def pack_transit(self, release):
        with tarfile.open(self.transit / f"{release}.tar.gz", "w:gz") as archive:
            for name, content in flat_tree(release).items():
                data = content.encode()
                member = tarfile.TarInfo(f"moodle-{release}/{name}")
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))

    def write(self, tree, files):
        for name, content in files.items():
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def ship(self, files):
        shutil.rmtree(self.source, ignore_errors=True)
        self.write(self.source, files)

    def run_entrypoint(self, release, **env):
        return subprocess.run(
            ["bash", str(ENTRYPOINT), "php-fpm"],
            env={**self.env, "MOODLE_RELEASE": release, **env},
            capture_output=True,
            text=True,
            check=False,
        )

    def start(self, release, **env):
        done = self.run_entrypoint(release, **env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def recorded(self):
        return read_text(str(self.code / ".bootstrap.done"))

    def php_calls(self):
        log = self.php_log.read_text()  # nocheck: cache-read  the php stub appends to this tempdir log while the test runs
        return log.replace(f"{self.code}/", "").splitlines()

    def shipped_files_in_the_volume(self):
        return {
            name for name in {*LAYOUT_4, *LAYOUT_5} if (self.code / name).is_file()
        }

    def test_the_first_start_fills_the_code_volume(self):
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        self.assertEqual(self.shipped_files_in_the_volume(), set(LAYOUT_5))

    def test_the_first_start_asks_the_database_nothing(self):
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        self.assertEqual(self.php_calls(), [])

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
        self.assertEqual(self.recorded(), "4.5.11")

    def test_a_sibling_that_finishes_first_keeps_its_tree(self):
        self.ship(LAYOUT_5)
        installed = {"public/local/installed/version.php": "written by the deploy"}
        self.write(self.code, installed)
        self.sibling_finishes_during_the_copy("5.3")
        self.start("5.3")
        self.assertTrue((self.code / "public/local/installed/version.php").is_file())
        self.assertFalse(self.stage.exists())
        self.assertEqual(read_text(str(self.sentinel)), "5.3")

    def test_an_image_older_than_the_recorded_release_refuses_to_replace_it(self):
        self.upgrade_path.write_text("5.10.0 4.4.0\n")
        self.ship(LAYOUT_5)
        self.start("5.10.0")
        self.ship(LAYOUT_4)
        done = self.run_entrypoint("5.9.2")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("5.10.0", done.stderr)
        self.assertEqual(self.shipped_files_in_the_volume(), set(LAYOUT_5))
        self.assertEqual(self.recorded(), "5.10.0")

    def test_a_site_at_the_minimum_source_upgrades_without_a_transit(self):
        self.write(self.code, flat_tree("4.5.4"))
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        self.assertEqual(self.php_calls(), ["5.3|admin/cli/upgrade.php --is-pending"])

    def test_a_site_below_the_minimum_source_passes_through_the_transit_release(self):
        self.write(self.code, flat_tree("4.3.2"))
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        self.assertEqual(
            self.php_calls(),
            [
                "4.5.15|admin/cli/upgrade.php --non-interactive",
                "5.3|admin/cli/upgrade.php --is-pending",
            ],
        )

    def test_the_transit_ends_on_the_pinned_tree_and_release(self):
        self.write(self.code, flat_tree("4.3.2"))
        self.ship(LAYOUT_5)
        self.start("5.3.0")
        self.assertEqual(self.shipped_files_in_the_volume(), set(LAYOUT_5))
        self.assertEqual(self.recorded(), "5.3.0")

    def test_the_transit_tree_runs_with_the_role_config(self):
        self.write(self.code, flat_tree("4.3.2"))
        self.ship(LAYOUT_5)
        self.run_entrypoint("5.3.0", STUB_UPGRADE_RC="1")
        self.assertEqual(read_text(str(self.code / "config.php")), ROLE_CONFIG)

    def test_a_failed_transit_upgrade_keeps_the_site_release_recorded(self):
        self.write(self.code, flat_tree("4.3.2"))
        self.ship(LAYOUT_5)
        done = self.run_entrypoint("5.3.0", STUB_UPGRADE_RC="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(self.recorded(), "4.3.2")

    def test_a_restart_after_a_failed_transit_repeats_it(self):
        self.write(self.code, flat_tree("4.3.2"))
        self.ship(LAYOUT_5)
        self.run_entrypoint("5.3.0", STUB_UPGRADE_RC="1")
        self.start("5.3.0")
        upgrades = [call for call in self.php_calls() if "--non-interactive" in call]
        self.assertEqual([call.split("|")[0] for call in upgrades], ["4.5.15"] * 2)
        self.assertEqual(self.recorded(), "5.3.0")

    def test_a_bitnami_tree_is_named_and_migrated(self):
        self.write(self.code, {**flat_tree("4.3.2"), "config.php": BITNAMI_CONFIG})
        self.ship(LAYOUT_5)
        done = self.start("5.3.0")
        self.assertIn("Bitnami layout", done.stderr)
        self.assertEqual(read_text(str(self.code / "config.php")), ROLE_CONFIG)
        self.assertEqual(self.recorded(), "5.3.0")

    def test_a_site_older_than_every_upgrade_source_stops_and_keeps_its_tree(self):
        self.write(self.code, flat_tree("3.11.8"))
        self.ship(LAYOUT_5)
        done = self.run_entrypoint("5.3.0")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("3.11.8", done.stderr)
        self.assertEqual(read_text(str(self.code / "version.php")), version_php("3.11.8"))
        self.assertEqual(self.php_calls(), [])

    def test_a_tree_without_a_release_stops_and_keeps_its_tree(self):
        self.write(self.code, {"version.php": "<?php\n"})
        self.ship(LAYOUT_5)
        done = self.run_entrypoint("5.3.0")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(read_text(str(self.code / "version.php")), "<?php\n")

    def test_an_existing_site_without_an_installed_database_refuses_to_start(self):
        self.write(self.code, flat_tree("4.5.4"))
        self.ship(LAYOUT_5)
        done = self.run_entrypoint("5.3.0", STUB_PENDING_RC="1")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("4.5.4", done.stderr)
        self.assertEqual(self.recorded(), "4.5.4")


if __name__ == "__main__":
    unittest.main()
