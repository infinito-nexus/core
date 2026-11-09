from __future__ import annotations

import json
import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

ROLE = PROJECT_ROOT / "roles" / "web-opt-rdr-domains"


class TestRedirectLoopRendersShallow(unittest.TestCase):
    def test_both_files_of_every_source_render_through_template_shallow(
        self,
    ) -> None:
        tasks = load_yaml_any(str(ROLE / ROLE_FILE_TASKS_MAIN))
        [loop_task] = [
            task for task in tasks if "redirect_source" in task.get("vars", {})
        ]
        files = loop_task["vars"]["redirect_source"]["files"]
        self.assertEqual(files.count("lookup('template_shallow', "), 2)
        self.assertNotIn("lookup('template', ", json.dumps(loop_task))

    def test_the_lookup_is_the_shared_plugin_not_a_role_local_copy(self) -> None:
        self.assertTrue(
            (PROJECT_ROOT / "plugins" / "lookup" / "template_shallow.py").is_file()
        )
        self.assertFalse((ROLE / "lookup_plugins").exists())


if __name__ == "__main__":
    unittest.main()
