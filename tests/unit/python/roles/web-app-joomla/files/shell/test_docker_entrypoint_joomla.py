import contextlib
import os
import signal
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

SHELL_DIR = PROJECT_ROOT / "roles/web-app-joomla/files/shell"
ENTRYPOINT = SHELL_DIR / "docker-entrypoint-joomla.sh"
SERVE = "serve apache2-foreground"

STOCK_STUB = """#!/usr/bin/env bash
printf 'call %s\\n' "$*" >> "${STUB_CALLS}"
case "$1" in apache2*) ;; *) exit 0 ;; esac
case "${2-}" in -v | -V | -h | -t | -T) exit 0 ;; esac
cd "${JOOMLA_WEBROOT}" || exit 9
if [ -e .joomla-initializing ]; then
  echo '[ERROR] Initialization is incomplete or another initializer is active.' >&2
  exit 1
fi
if [ ! -s configuration.php ]; then
  if [ "${STUB_DB}" != up ]; then
    echo '[ERROR] Database initialization failed (exit 1).' >&2
    exit 1
  fi
  mkdir .joomla-initializing
  printf 'init\\n' >> "${STUB_CALLS}"
  mkdir -p installation
  touch index.php installation/joomla.php joomla.xml robots.txt.dist
  sleep "${STUB_SETUP_DELAY}"
  if [ "${STUB_INSTALL}" = broken ]; then
    echo '[ERROR] Automatic Joomla installation failed (exit 1).' >&2
    exit 1
  fi
  echo '<?php' > configuration.php
  sleep "${STUB_FINISH_DELAY}"
  case "${STUB_INSTALL}" in
    crash)
      echo '[ERROR] Automatic Joomla installation failed (exit 255).' >&2
      exit 1 ;;
    nfs)
      echo ' [ERROR] Unable to delete installation folder!'
      exit 1 ;;
    nfs-unowned)
      echo ' [ERROR] Unable to delete installation folder!'
      echo '[ERROR] Failed to correct ownership after initialization.' >&2
      exit 1 ;;
  esac
  rm -rf installation joomla.xml
  mv robots.txt.dist robots.txt
  rmdir .joomla-initializing
fi
printf 'serve %s\\n' "$*" >> "${STUB_CALLS}"
"""

RM_STUB = """#!/usr/bin/env bash
if [ "${STUB_RM_FAIL}" = 1 ]; then
  case "$*" in *installation*) echo 'rm: Device or resource busy' >&2; exit 1 ;; esac
fi
PATH="${STUB_REAL_PATH}" exec rm "$@"
"""


class TestJoomlaEntrypoint(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.webroot = self.root / "html"
        self.webroot.mkdir()
        bin_dir = self.root / "bin"
        bin_dir.mkdir()
        self.stock = self.root / "entrypoint.sh"
        for path, body in {self.stock: STOCK_STUB, bin_dir / "rm": RM_STUB}.items():
            path.write_text(body)
            path.chmod(0o755)
        self.ready = self.webroot / ".infinito-init.ready"
        self.marker = self.webroot / ".joomla-initializing"
        self.lock = self.webroot / ".infinito-init.lock"
        self.pending = self.webroot / ".infinito-init.cleanup"
        self.env = {
            **os.environ,
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_REAL_PATH": os.environ["PATH"],
            "JOOMLA_WEBROOT": str(self.webroot),
            "JOOMLA_STOCK_ENTRYPOINT": str(self.stock),
            "JOOMLA_INIT_READY_FILE": str(self.ready),
            "JOOMLA_INIT_LOCK_STALE_SECONDS": "60",
            "STUB_DB": "up",
            "STUB_INSTALL": "ok",
            "STUB_SETUP_DELAY": "0",
            "STUB_FINISH_DELAY": "0",
            "STUB_RM_FAIL": "0",
        }

    def spawn(self, name, **env):
        log = self.root / f"{name}.log"
        log.touch()
        with (self.root / f"{name}.err").open("a") as err:
            process = subprocess.Popen(
                ["bash", str(ENTRYPOINT), "apache2-foreground"],
                env={**self.env, "STUB_CALLS": str(log), **env},
                stdout=subprocess.DEVNULL,
                stderr=err,
                start_new_session=True,
            )
        self.addCleanup(self.kill_group, process)
        return process

    def kill_group(self, process):
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()

    def run_entrypoint(self, **env):
        return self.spawn("calls", **env).wait(timeout=60)

    def text(self, name):
        path = self.root / name
        return path.read_text(encoding="utf-8")  # nocheck: cache-read tempdir

    def calls(self, name):
        return self.text(f"{name}.log").splitlines()

    def wait_for(self, path):
        deadline = time.monotonic() + 30
        while not path.exists() and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertTrue(path.exists())

    def leave_stuck_volume(self):
        for name in ("installation", ".joomla-initializing", ".infinito-init.lock"):
            (self.webroot / name).mkdir()
        (self.webroot / "configuration.php").write_text("<?php\n")
        (self.webroot / "robots.txt.dist").write_text("User-agent: *\n")
        hour_ago = time.time() - 3600
        os.utime(self.lock, (hour_ago, hour_ago))

    def assert_site_down(self):
        self.assertTrue(self.marker.is_dir())
        self.assertFalse(self.ready.exists())
        self.assertNotIn(SERVE, self.calls("calls"))

    def test_a_fresh_volume_is_set_up_once_before_the_server_starts(self):
        self.assertEqual(self.run_entrypoint(), 0)
        self.assertEqual(self.calls("calls").count("init"), 1)
        self.assertEqual(self.calls("calls")[-1], SERVE)
        self.assertTrue(self.ready.exists())
        self.assertFalse(self.lock.exists())

    def test_the_nfs_installation_folder_failure_finishes_the_cleanup(self):
        self.assertEqual(self.run_entrypoint(STUB_INSTALL="nfs"), 0)
        for name in ("installation", "joomla.xml", "robots.txt.dist"):
            self.assertFalse((self.webroot / name).exists(), name)
        self.assertTrue((self.webroot / "robots.txt").is_file())
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.pending.exists())
        self.assertEqual(self.calls("calls")[-1], SERVE)

    def test_an_install_crash_after_the_config_was_written_keeps_the_site_down(self):
        self.assertNotEqual(self.run_entrypoint(STUB_INSTALL="crash"), 0)
        self.assert_site_down()
        self.assertTrue((self.webroot / "installation").is_dir())
        self.assertFalse(self.pending.exists())
        self.assertFalse(self.lock.exists())

    def test_a_failed_ownership_repair_keeps_the_site_down(self):
        self.assertNotEqual(self.run_entrypoint(STUB_INSTALL="nfs-unowned"), 0)
        self.assert_site_down()
        self.assertFalse(self.pending.exists())

    def test_a_failed_install_keeps_the_server_down_and_releases_the_lock(self):
        self.assertNotEqual(self.run_entrypoint(STUB_INSTALL="broken"), 0)
        self.assert_site_down()
        self.assertFalse(self.lock.exists())

    def test_a_restart_after_a_database_outage_sets_the_site_up(self):
        self.assertNotEqual(self.run_entrypoint(STUB_DB="down"), 0)
        self.assertEqual(self.run_entrypoint(), 0)
        self.assertEqual(self.calls("calls").count("init"), 1)
        self.assertEqual(self.calls("calls")[-1], SERVE)

    def test_an_existing_installation_starts_without_setup(self):
        (self.webroot / "configuration.php").write_text("<?php\n")
        self.assertEqual(self.run_entrypoint(), 0)
        self.assertNotIn("init", self.calls("calls"))
        self.assertEqual(self.calls("calls")[-1], SERVE)

    def test_a_follower_starts_only_after_the_leader_finished(self):
        leader = self.spawn("leader", STUB_FINISH_DELAY="3")
        self.wait_for(self.lock)
        follower = self.spawn("follower")
        self.assertEqual(leader.wait(timeout=60), 0)
        self.assertEqual(follower.wait(timeout=60), 0)
        self.assertEqual(self.calls("follower"), ["call apache2-foreground", SERVE])

    def test_a_live_leader_keeps_its_lock_past_the_stale_age(self):
        stale = {"JOOMLA_INIT_LOCK_STALE_SECONDS": "3"}
        leader = self.spawn("leader", STUB_SETUP_DELAY="8", **stale)
        self.wait_for(self.lock / "owner")
        follower = self.spawn("follower", **stale)
        self.assertEqual(leader.wait(timeout=60), 0)
        self.assertEqual(follower.wait(timeout=60), 0)
        self.assertEqual(self.calls("leader").count("init"), 1)
        self.assertEqual(self.calls("follower"), ["call apache2-foreground", SERVE])

    def test_a_stale_lock_on_a_fresh_volume_is_taken_over(self):
        self.lock.mkdir()
        hour_ago = time.time() - 3600
        os.utime(self.lock, (hour_ago, hour_ago))
        self.assertEqual(self.run_entrypoint(), 0)
        self.assertEqual(self.calls("calls").count("init"), 1)
        self.assertEqual(self.calls("calls")[-1], SERVE)

    def test_a_stuck_volume_names_the_manual_step_instead_of_starting(self):
        self.leave_stuck_volume()
        self.assertNotEqual(self.run_entrypoint(), 0)
        self.assert_site_down()
        self.assertIn(f"touch {self.pending}", self.text("calls.err"))
        self.assertFalse(self.lock.exists())

    def test_a_stuck_volume_recovers_once_the_manual_step_is_done(self):
        self.leave_stuck_volume()
        self.pending.touch()
        self.assertEqual(self.run_entrypoint(), 0)
        self.assertFalse((self.webroot / "installation").exists())
        self.assertTrue((self.webroot / "robots.txt").is_file())
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.calls("calls")[-1], SERVE)

    def test_a_failed_folder_removal_is_retried_on_the_next_start(self):
        failed = self.run_entrypoint(STUB_INSTALL="nfs", STUB_RM_FAIL="1")
        self.assertNotEqual(failed, 0)
        self.assert_site_down()
        self.assertTrue(self.pending.exists())
        self.assertEqual(self.run_entrypoint(), 0)
        self.assertFalse((self.webroot / "installation").exists())
        self.assertFalse(self.marker.exists())
        self.assertEqual(self.calls("calls").count("init"), 1)
        self.assertEqual(self.calls("calls")[-1], SERVE)

    def test_sigterm_during_setup_releases_the_lock(self):
        leader = self.spawn("calls", STUB_SETUP_DELAY="10")
        self.wait_for(self.lock / "owner")
        leader.send_signal(signal.SIGTERM)
        self.assertEqual(leader.wait(timeout=30), 143)
        self.assertFalse(self.lock.exists())


if __name__ == "__main__":
    unittest.main()
