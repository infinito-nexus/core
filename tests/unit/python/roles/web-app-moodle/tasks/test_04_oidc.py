import filecmp
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/web-app-moodle/tasks/04_oidc.yml"
SYNC_TASK = "📋 Sync the auth_oidc plugin from the image into the code volume"
PLUGIN_V2 = {
    "version.php": "<?php\n$plugin->version = 2;\n",
    "classes/oidcclient.php": "<?php\n// v2\n",
}
PLUGIN_V1 = {
    "version.php": "<?php\n$plugin->version = 1;\n",
    "classes/oidcclient.php": "<?php\n// v1\n",
    "classes/dropped.php": "<?php\n// only in v1\n",
}


def sync_script(source, target, staging):
    task = next(
        task for task in load_yaml_any(str(TASKS)) if task.get("name") == SYNC_TASK
    )
    body = re.search(r"sh -c '(.*)'\s*$", task["shell"], re.DOTALL).group(1)
    return (
        Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        .from_string(body)
        .render(
            MOODLE_OIDC_PLUGIN_SOURCE_DIR=str(source),
            MOODLE_OIDC_PLUGIN_DIR=str(target),
            MOODLE_OIDC_PLUGIN_SYNC_DIR=str(staging),
        )
    )


class TestOidcPluginSync(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.source = root / "source/public/auth/oidc"
        self.target = root / "code/public/auth/oidc"
        self.staging = root / "code/.auth_oidc.sync"
        self.target.parent.mkdir(parents=True)

    def fill(self, tree, files):
        for name, content in files.items():
            path = tree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)

    def files_in(self, tree):
        return {
            path.relative_to(tree).as_posix()
            for path in tree.rglob("*")  # nocheck: project-walk  test tempdir
            if path.is_file()
        }

    def assert_same_tree(self, left, right):
        names = self.files_in(left)
        self.assertEqual(names, self.files_in(right))
        _, mismatch, errors = filecmp.cmpfiles(
            left, right, sorted(names), shallow=False
        )
        self.assertEqual((mismatch, errors), ([], []))

    def sync(self):
        return subprocess.run(
            ["sh", "-c", sync_script(self.source, self.target, self.staging)],
            capture_output=True,
            text=True,
            check=False,
        )

    def test_a_volume_without_the_plugin_receives_it(self):
        self.fill(self.source, PLUGIN_V2)
        done = self.sync()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("synced", done.stdout)
        self.assert_same_tree(self.target, self.source)

    def test_a_volume_that_matches_the_image_reports_no_change(self):
        self.fill(self.source, PLUGIN_V2)
        self.fill(self.target, PLUGIN_V2)
        done = self.sync()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("synced", done.stdout)

    def test_a_second_run_reports_no_change(self):
        self.fill(self.source, PLUGIN_V2)
        self.sync()
        done = self.sync()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("synced", done.stdout)

    def test_files_a_newer_plugin_dropped_leave_the_volume(self):
        self.fill(self.source, PLUGIN_V2)
        self.fill(self.target, PLUGIN_V1)
        done = self.sync()
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assert_same_tree(self.target, self.source)
        self.assertFalse(self.staging.exists())

    def test_a_failed_copy_keeps_the_plugin_the_volume_held(self):
        self.fill(self.target, PLUGIN_V1)
        done = self.sync()
        self.assertNotEqual(done.returncode, 0)
        self.assertNotIn("synced", done.stdout)
        self.assertEqual(self.files_in(self.target), set(PLUGIN_V1))


if __name__ == "__main__":
    unittest.main()
