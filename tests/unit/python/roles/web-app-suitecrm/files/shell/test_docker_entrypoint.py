import grp
import os
import pwd
import subprocess
import tempfile
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

ENTRYPOINT = PROJECT_ROOT / "roles/web-app-suitecrm/files/shell/docker-entrypoint.sh"
PINNED = "8.10.2"
PACKAGE = f"SuiteCRM-{PINNED}"
UPGRADE = f"bin/console suitecrm:app:upgrade -n -t {PACKAGE}"
FINALIZE = f"bin/console suitecrm:app:upgrade-finalize -n -t {PACKAGE} -m keep"

PHP_STUB = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "${STUB_PHP_LOG}"
case "$*" in
  *suitecrm:app:upgrade-finalize*) exit "${STUB_FINALIZE_RC}" ;;
  *"suitecrm:app:upgrade "*)
    compgen -G "tmp/package/upgrade/*.zip" > /dev/null || exit 9
    cp "${SUITECRM_SEED_DIR}/VERSION" VERSION
    rm -f public/installed.flag .tree-seeded
    exit "${STUB_UPGRADE_RC}"
    ;;
esac
exit 0
"""

ZIP_STUB = """#!/usr/bin/env bash
pwd > "${4}"
"""


class TestSuiteCrmEntrypoint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.code = self.root / "code"
        self.code.mkdir()
        self.seed = self.root / "seed"
        self.plant(self.seed, PINNED)
        self.php_log = self.root / "php.log"
        self.php_log.touch()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        for name, body in {"php": PHP_STUB, "zip": ZIP_STUB}.items():
            stub = bin_dir / name
            stub.write_text(body)
            stub.chmod(0o755)
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "SUITECRM_APP_DIR": str(self.code),
            "SUITECRM_SEED_DIR": str(self.seed),
            "SUITECRM_APP_VERSION": PINNED,
            "SUITECRM_WEB_USER": pwd.getpwuid(os.getuid()).pw_name,
            "SUITECRM_WEB_GROUP": grp.getgrgid(os.getgid()).gr_name,
            "SUITECRM_ADMIN_USERNAME": "administrator",
            "SUITECRM_ADMIN_PASSWORD": "stub",
            "SUITECRM_DB_USER": "suitecrm",
            "SUITECRM_DB_PASSWORD": "stub",
            "SUITECRM_DB_HOST": "database",
            "SUITECRM_DB_PORT": "3306",
            "SUITECRM_DB_NAME": "suitecrm",
            "SUITECRM_URL": "https://suitecrm.example",
            "STUB_PHP_LOG": str(self.php_log),
            "STUB_UPGRADE_RC": "0",
            "STUB_FINALIZE_RC": "0",
        }

    def plant(self, tree, version):
        for directory in ("public/legacy", "logs", "extensions"):
            (tree / directory).mkdir(parents=True, exist_ok=True)
        (tree / "VERSION").write_text(f"{version}\n")

    def install(self, version):
        self.plant(self.code, version)
        (self.code / "public/installed.flag").write_text("installed\n")

    def run_entrypoint(self, **env):
        return subprocess.run(
            ["sh", str(ENTRYPOINT), "true"],
            cwd=self.code,
            env={**self.env, **env},
            capture_output=True,
            text=True,
            check=False,
        )

    def start(self):
        done = self.run_entrypoint()
        self.assertEqual(done.returncode, 0, done.stderr)
        return done

    def text(self, name):
        path = self.code / name
        return path.read_text(encoding="utf-8").strip()  # nocheck: cache-read tempdir

    def php_calls(self):
        log = self.php_log.read_text(encoding="utf-8")  # nocheck: cache-read tempdir
        return log.splitlines()

    def upgrade_calls(self):
        return [call for call in self.php_calls() if "suitecrm:app:upgrade" in call]

    def test_a_fresh_volume_is_seeded_and_stamped_with_the_seeded_version(self):
        self.start()
        self.assertEqual(self.text("VERSION"), PINNED)
        self.assertEqual(self.text(".tree-seeded"), PINNED)
        self.assertEqual(self.upgrade_calls(), [])

    def test_an_installed_tree_below_the_pin_runs_the_suitecrm_upgrade(self):
        self.install("8.9.1")
        self.start()
        self.assertEqual(self.upgrade_calls(), [UPGRADE, FINALIZE])

    def test_the_upgraded_tree_is_stamped_with_the_version_it_now_has(self):
        self.install("8.9.1")
        self.start()
        self.assertEqual(self.text(".tree-seeded"), PINNED)
        self.assertTrue((self.code / "public/installed.flag").is_file())
        self.assertFalse((self.code / "tmp/package/upgrade").exists())

    def test_a_stamp_claiming_the_pin_does_not_hide_an_older_tree(self):
        self.install("8.9.1")
        (self.code / ".tree-seeded").write_text(f"{PINNED}\n")
        self.start()
        self.assertEqual(self.upgrade_calls(), [UPGRADE, FINALIZE])

    def test_a_tree_on_the_pin_is_left_alone(self):
        self.install(PINNED)
        self.start()
        self.assertEqual(self.upgrade_calls(), [])
        self.assertFalse(any("suitecrm:app:install" in c for c in self.php_calls()))
        self.assertEqual(self.text(".tree-seeded"), PINNED)

    def test_a_tree_newer_than_the_pin_refuses_to_start(self):
        self.install("8.10.10")
        done = self.run_entrypoint()
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("8.10.10", done.stderr)
        self.assertEqual(self.text("VERSION"), "8.10.10")
        self.assertEqual(self.upgrade_calls(), [])

    def test_a_restart_after_a_failed_finalize_repeats_the_upgrade(self):
        self.install("8.9.1")
        failed = self.run_entrypoint(STUB_FINALIZE_RC="1")
        self.assertNotEqual(failed.returncode, 0)
        self.start()
        self.assertEqual(self.upgrade_calls(), [UPGRADE, FINALIZE] * 2)
        self.assertEqual(self.text(".tree-seeded"), PINNED)

    def test_an_interrupted_upgrade_resumes_instead_of_reinstalling(self):
        self.install("8.9.1")
        failed = self.run_entrypoint(STUB_UPGRADE_RC="1")
        self.assertNotEqual(failed.returncode, 0)
        self.assertFalse((self.code / ".tree-seeded").exists())
        self.start()
        self.assertFalse(any("suitecrm:app:install" in c for c in self.php_calls()))
        self.assertEqual(self.upgrade_calls(), [UPGRADE, UPGRADE, FINALIZE])
        self.assertTrue((self.code / "public/installed.flag").is_file())


if __name__ == "__main__":
    unittest.main()
