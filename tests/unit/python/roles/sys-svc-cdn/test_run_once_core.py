from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

CDN_DIR = PROJECT_ROOT / "roles" / "sys-svc-cdn"
MAIN = CDN_DIR / ROLE_FILE_TASKS_MAIN
CORE = CDN_DIR / "tasks" / "00_core.yml"
GUARD = "run_once_sys_svc_cdn is not defined"


class TestTheSharedTreeIsEnsuredOncePerRun(unittest.TestCase):
    def setUp(self) -> None:
        self.main = load_yaml_any(str(MAIN))
        self.core = load_yaml_any(str(CORE))

    def test_a_repeated_include_skips_one_guarded_task(self) -> None:
        guarded = [
            task for task in self.main if "when" in task and GUARD in str(task["when"])
        ]
        self.assertEqual(guarded, [{"include_tasks": "00_core.yml", "when": GUARD}])

    def test_the_guarded_include_ensures_the_shared_tree_then_sets_the_flag(
        self,
    ) -> None:
        self.assertEqual(len(self.core), 2)
        self.assertEqual(
            self.core[0]["directory_batch"],
            {"paths": "{{ CDN_GLOBAL_DIRS }}", "mode": "0755"},
        )
        self.assertEqual(self.core[1], {"include_tasks": "utils/once/flag.yml"})

    def test_the_role_tree_is_still_ensured_on_every_include(self) -> None:
        ensures = [task for task in self.main if "directory_batch" in task]
        self.assertEqual(len(ensures), 1)
        self.assertEqual(
            ensures[0]["directory_batch"],
            {"paths": "{{ CDN_ROLE_DIRS }}", "mode": "0755"},
        )
        self.assertNotIn("run_once", str(ensures[0]["when"]))


if __name__ == "__main__":
    unittest.main()
