"""Lint: every role hook file belongs to a hook point that a stage runs.

A role registers for a hook point by shipping ``tasks/hooks/<point>.yml``;
``tasks/utils/hooks/run.yml`` runs it wherever a stage sets
``stage_hook_point: <point>``. A hook file whose name matches no hook point
would never run, so this test rejects it.
"""

from __future__ import annotations

import re
import unittest

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

HOOK_POINT_RE = re.compile(r"^\s*stage_hook_point:\s*([a-z_]+)\s*$", re.MULTILINE)
CALLERS = [
    *sorted((PROJECT_ROOT / "tasks" / "stages").glob("*.yml")),
    PROJECT_ROOT / "roles" / "sys-stk-backend" / ROLE_FILE_TASKS_MAIN,
]


def hook_points() -> set[str]:
    return {
        point
        for caller in CALLERS
        for point in HOOK_POINT_RE.findall(read_text(str(caller)))
    }


class TestStageHooks(unittest.TestCase):
    def test_hook_points_exist(self):
        self.assertEqual(
            hook_points(), {"backend", "constructor", "destructor", "destructor_post"}
        )

    def test_every_hook_file_names_a_hook_point(self):
        points = hook_points()
        hooks = sorted((PROJECT_ROOT / "roles").glob("*/tasks/hooks/*.yml"))
        self.assertTrue(hooks)
        for hook in hooks:
            with self.subTest(hook=str(hook.relative_to(PROJECT_ROOT))):
                self.assertIn(hook.stem, points)


if __name__ == "__main__":
    unittest.main()
