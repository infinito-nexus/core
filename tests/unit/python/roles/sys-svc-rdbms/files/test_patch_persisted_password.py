"""Guards around the persisted database password patch.

``roles/sys-svc-rdbms/files/shell/patch_persisted_password.sh`` rewrites a
credential inside a config file on an application's own volume, on whichever
node holds it. These tests run the script against a stubbed ``container``
rather than trusting a reading of it: it has to find the volume, refuse to
touch a mountpoint without the config, and leave a password the app can use.

The parameters come from the environment, so each consuming role's own
``patch_db_credentials.yml`` supplies them here exactly as the task would.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "roles/sys-svc-rdbms/files/shell/patch_persisted_password.sh"

CONSUMERS: ClassVar = {
    "matomo": "[database]\npassword = OLDPW\nhost = db\n",
    "moodle": "<?php\n$CFG->dbpass = 'OLDPW';\n$CFG->dbname = 'moodle';\n",
    "nextcloud": "<?php\n  'dbpassword' => 'OLDPW',\n  'dbname' => 'nc',\n",
}


def _caller_vars(app: str) -> dict:
    """Return the parameters a consuming role hands to the shared task.

    Args:
        app: the web-app suffix of the consuming role.
    """
    caller = load_yaml_any(
        str(PROJECT_ROOT / f"roles/web-app-{app}/tasks/utils/patch/db_credentials.yml")
    )
    return caller[0]["vars"]


def _script_env(app: str, bindir: Path) -> dict[str, str]:
    """Return the environment the task hands the script for one consumer.

    Args:
        app: the web-app suffix of the consuming role.
        bindir: directory holding the stubbed ``container``.
    """
    params = _caller_vars(app)
    return {
        **os.environ,
        "PATH": f"{bindir}:{os.environ['PATH']}",
        "PATCH_VOLUME": params["patch_volume"],
        "PATCH_CONFIG_REL": params["patch_config_rel"],
        "PATCH_EXPRESSION": params["patch_expression"],
        "PATCH_PASSWORD": "NEWPW",
    }


def _write_stub(bindir: Path, volumes: dict[str, Path]) -> None:
    """Write a ``container`` that knows only the volumes it is given.

    Args:
        bindir: directory placed first on PATH.
        volumes: volume name to mountpoint.
    """
    bindir.mkdir(parents=True, exist_ok=True)
    listed = "\n".join(f'    "name=^{n}$") echo "{n}";;' for n in volumes)
    inspected = "\n".join(f'    "{n}") echo "{p}";;' for n, p in volumes.items())
    stub = bindir / "container"
    stub.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "volume" ] && [ "$2" = "ls" ]; then\n'
        f'  case "$5" in\n{listed}\n    *) : ;;\n  esac\n  exit 0\nfi\n'
        'if [ "$1" = "volume" ] && [ "$2" = "inspect" ]; then\n'
        f'  case "$5" in\n{inspected}\n    *) exit 1;;\n  esac\n  exit 0\nfi\n'
        "exit 1\n"
    )
    stub.chmod(0o755)


class TestPatchPersistedPassword(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _run(self, app: str, *, volume_exists: bool, config_exists: bool):
        params = _caller_vars(app)
        mount = self.tmp / "mount"
        if config_exists:
            target = mount / params["patch_config_rel"]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(CONSUMERS[app])
        bindir = self.tmp / "bin"
        _write_stub(bindir, {params["patch_volume"]: mount} if volume_exists else {})
        proc = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env=_script_env(app, bindir),
            capture_output=True,
            text=True,
            check=False,
        )
        target = mount / params["patch_config_rel"]
        content = ""
        if config_exists:
            content = target.read_text()  # nocheck: cache-read  shell just rewrote it
        return proc, content

    def test_it_replaces_the_password_each_consumer_persists(self) -> None:
        for app in CONSUMERS:
            with self.subTest(app=app):
                proc, content = self._run(app, volume_exists=True, config_exists=True)
                self.assertEqual(0, proc.returncode, proc.stderr)
                self.assertIn("NEWPW", content)
                self.assertNotIn("OLDPW", content)
                self.assertIn("PATCHED", proc.stdout)

    def test_a_node_without_the_volume_reports_no_change(self) -> None:
        """Every swarm node runs this; only the one holding the volume acts."""
        for app in CONSUMERS:
            with self.subTest(app=app):
                proc, _ = self._run(app, volume_exists=False, config_exists=False)
                self.assertEqual(0, proc.returncode, proc.stderr)
                self.assertNotIn("PATCHED", proc.stdout)

    def test_a_volume_without_the_config_reports_no_change(self) -> None:
        """The volume exists before the app has ever written its config."""
        for app in CONSUMERS:
            with self.subTest(app=app):
                proc, _ = self._run(app, volume_exists=True, config_exists=False)
                self.assertEqual(0, proc.returncode, proc.stderr)
                self.assertNotIn("PATCHED", proc.stdout)

    def test_the_placeholder_never_survives_into_the_config(self) -> None:
        """Bash does not expand a ``${...}`` that arrives inside a variable."""
        for app in CONSUMERS:
            with self.subTest(app=app):
                _, content = self._run(app, volume_exists=True, config_exists=True)
                self.assertNotIn("@PASSWORD@", content)
                self.assertNotIn("PATCH_PASSWORD", content)

    def test_it_refuses_to_run_without_its_parameters(self) -> None:
        """A silent no-op would look exactly like a node without the volume."""
        proc = subprocess.run(
            ["/bin/bash", str(SCRIPT)],
            env={"PATH": os.environ["PATH"]},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("PATCH_VOLUME", proc.stderr)


if __name__ == "__main__":
    unittest.main()
