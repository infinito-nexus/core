from __future__ import annotations

import unittest

from ._script_shims import ScriptRunner

SCRIPTS = (
    ("deploy.sh", ("devices.yml",)),
    ("host.sh", ("update",)),
    ("workspace.sh", ()),
    ("members.sh", ()),
    ("user.sh", ()),
    ("store-credentials.sh", ()),
    ("task-entities.sh", ()),
    ("announce-owners.sh", ()),
    ("prune-exports.sh", ()),
)


class TemplateScriptTests(unittest.TestCase):
    def setUp(self):
        self.runner = ScriptRunner()
        self.addCleanup(self.runner.cleanup)

    def test_each_template_script_refuses_extra_arguments(self):
        for script, args in SCRIPTS:
            with self.subTest(script):
                run = self.runner.run(script, {}, (*args, "--limit=all"))
                self.assertEqual(run.returncode, 2, run.stderr)
                self.assertIn(
                    f"{script}: unexpected argument '--limit=all'", run.stderr
                )
                self.assertEqual(self.runner.calls(), [])

    def test_negative_control_a_script_without_its_argument_is_refused_too(self):
        run = self.runner.run("deploy.sh", {}, ())
        self.assertEqual(run.returncode, 2)
        self.assertIn("deploy.sh: expects 1 argument(s), got 0", run.stderr)


if __name__ == "__main__":
    unittest.main()
