from __future__ import annotations

import contextlib
import json
import os
import shutil
import unittest
import unittest.mock as mock
from pathlib import Path

from ._fake_provision import harness_directory, load

admission = load("provision.admission")


class TestExecPlan(unittest.TestCase):
    def ran(self, files, linked=None):
        """Args:
            files: the task files of the plan.
            linked: the link check of the exec helper, the real one for None.

        Returns:
            The argv the exec helper started, ``[]`` when it refused, in a
            task directory with a value file behind a planted link and a
            directory link.
        """
        base = harness_directory()
        self.addCleanup(shutil.rmtree, base)
        task = base / "task"
        task.mkdir()
        (base / "outside").write_text("x", encoding="utf-8")
        (task / "values.tfvars.json").symlink_to(base / "outside")
        (task / "dirlink").symlink_to(base)
        (task / "backend.tfbackend").write_text("x", encoding="utf-8")
        reader, writer = os.pipe()
        with os.fdopen(writer, "w", encoding="utf-8") as handle:
            json.dump(
                {"argv": ["tofu"], "env": {}, "cwd": str(task), "files": files}, handle
            )
        self.addCleanup(os.chdir, Path.cwd())
        started = []
        check = admission.sandbox.linked if linked is None else linked
        with (
            mock.patch.object(admission.sandbox, "linked", check),
            contextlib.suppress(SystemExit),
        ):
            admission.exec_plan(reader, lambda _path, argv, _env: started.append(argv))
        return started

    def test_a_task_file_behind_a_link_is_refused_as_the_sandbox_uid(self):
        for files in (["values.tfvars.json"], ["dirlink/outside"]):
            with self.subTest(files=files):
                self.assertEqual(self.ran(files), [])
        self.assertEqual(self.ran(["backend.tfbackend"]), [["tofu"]])

    def test_negative_control_a_lexical_check_alone_runs_behind_the_link(self):
        self.assertEqual(
            self.ran(["values.tfvars.json"], lambda _task, _relative: False), [["tofu"]]
        )


if __name__ == "__main__":
    unittest.main()
