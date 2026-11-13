from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT

from .test_stage_steps import CORE, STAGE, _includes, _tasks

BRIDGE = "tasks/utils/stack.yml"
INSTANCE = "roles/svc-ai-mcp-adapter/tasks/instance.yml"
STAGED = (
    "web-app-baserow",
    "web-app-checkmk",
    "web-app-fider",
    "web-app-gitea",
    "web-app-jellyfin",
    "web-app-jenkins",
    "web-app-listmonk",
    "web-app-pretix",
    "web-app-snipe-it",
    "web-svc-libretranslate",
)


class TestStageMcpAdapter(unittest.TestCase):
    def test_each_role_stages_its_adapter_before_its_bridged_backend(self) -> None:
        for role in STAGED:
            with self.subTest(role=role):
                self.assertTrue((PROJECT_ROOT / "roles" / role / BRIDGE).is_file())
                self.assertIn(INSTANCE, _includes(role, STAGE))
                self.assertNotIn(INSTANCE, _includes(role, CORE))

    def test_each_stage_holds_only_the_gated_adapter_staging(self) -> None:
        for role in STAGED:
            with self.subTest(role=role):
                tasks = _tasks(role, STAGE)
                self.assertEqual(len(tasks), 1)
                self.assertIn("mcp_adapter_instance_dir", tasks[0].get("vars", {}))
                self.assertIn("_MCP_ENABLED", str(tasks[0].get("when")))


if __name__ == "__main__":
    unittest.main()
