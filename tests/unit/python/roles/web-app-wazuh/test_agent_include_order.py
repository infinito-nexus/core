import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

AGENT_ROLE = "sys-svc-wazuh-agent"
MANAGER_ROLE = "web-app-wazuh"
BACKEND_HOOK = PROJECT_ROOT / "roles" / AGENT_ROLE / "tasks" / "hooks" / "backend.yml"
MAIN_INCLUDE = f"{{{{ role_path }}}}/{ROLE_FILE_TASKS_MAIN}"
WAZUH_TASKS = PROJECT_ROOT / "roles" / MANAGER_ROLE / "tasks" / "00_core.yml"


def agent_includes(tasks):
    return [
        index
        for index, task in enumerate(tasks)
        if (task.get("include_role") or {}).get("name") == AGENT_ROLE
    ]


class TestAgentIncludeOrder(unittest.TestCase):
    def test_backend_hook_skips_the_agent_on_the_manager_host(self):
        tasks = load_yaml_any(str(BACKEND_HOOK))
        includes = [task for task in tasks if task.get("include_tasks") == MAIN_INCLUDE]
        self.assertEqual(len(includes), 1)
        self.assertIn(
            "WAZUH_AGENT_MANAGER_ROLE not in group_names", includes[0]["when"]
        )

    def test_manager_loads_the_agent_after_pre_registration(self):
        tasks = load_yaml_any(str(WAZUH_TASKS))
        includes = agent_includes(tasks)
        self.assertEqual(len(includes), 1)
        registration = [
            index
            for index, task in enumerate(tasks)
            if isinstance(task.get("include_tasks"), dict)
            and task["include_tasks"].get("file") == "02_agents.yml"
        ]
        self.assertEqual(len(registration), 1)
        self.assertLess(registration[0], includes[0])
        self.assertNotIn("when", tasks[includes[0]])


if __name__ == "__main__":
    unittest.main()
