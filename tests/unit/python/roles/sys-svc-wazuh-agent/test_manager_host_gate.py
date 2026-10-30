import unittest

import jinja2

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml, load_yaml_any
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN, ROLE_FILE_VARS_MAIN

ROLE = PROJECT_ROOT / "roles" / "sys-svc-wazuh-agent"
GATE_VARS = (
    "WAZUH_AGENT_MANAGER_ROLE",
    "WAZUH_AGENT_MANAGER_DEPLOYED",
    "WAZUH_AGENT_MANAGER_LOCAL",
)


def _bool(value):
    return (
        value
        if isinstance(value, bool)
        else str(value).strip().lower() in ("true", "yes", "1")
    )


class TestAgentOnlyOnTheManagerHost(unittest.TestCase):
    def setUp(self):
        self.env = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701 - renders Ansible conditions from YAML, never HTML
        self.env.filters["bool"] = _bool
        self.role_vars = load_yaml(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.tasks = load_yaml_any(str(ROLE / ROLE_FILE_TASKS_MAIN))

    def resolve(self, group_names, groups):
        values = {
            "group_names": group_names,
            "groups": groups,
            "WAZUH_AGENT_ENABLED": True,
        }
        for name in GATE_VARS:
            values[name] = self.env.from_string(self.role_vars[name]).render(values)
        return values

    def runs(self, task, values):
        conditions = [task["when"]] if isinstance(task["when"], str) else task["when"]
        return all(
            _bool(self.env.from_string("{{ " + condition + " }}").render(values))
            for condition in conditions
            if "run_once" not in condition
        )

    def core_include(self):
        return next(
            task for task in self.tasks if task.get("include_tasks") == "00_core.yml"
        )

    def skip_message(self, values):
        return [
            task["name"]
            for task in self.tasks
            if "ansible.builtin.debug" in task and self.runs(task, values)
        ]

    def test_manager_host_installs_the_agent(self):
        values = self.resolve(
            ["web-app-wazuh", "web-app-pixelfed"], {"web-app-wazuh": ["manager"]}
        )
        self.assertTrue(self.runs(self.core_include(), values))
        self.assertEqual(self.skip_message(values), [])

    def test_other_host_skips_with_one_message(self):
        values = self.resolve(
            ["web-app-pixelfed"],
            {"web-app-wazuh": ["manager"], "web-app-pixelfed": ["web2"]},
        )
        self.assertFalse(self.runs(self.core_include(), values))
        self.assertEqual(
            self.skip_message(values),
            ["⏭️ Skip the Wazuh agent: manager runs on another host"],
        )

    def test_no_manager_at_all_keeps_its_own_message(self):
        values = self.resolve(["web-app-pixelfed"], {"web-app-pixelfed": ["web2"]})
        self.assertFalse(self.runs(self.core_include(), values))
        self.assertEqual(
            self.skip_message(values),
            ["⏭️ Skip the Wazuh agent: no manager in this deployment"],
        )


if __name__ == "__main__":
    unittest.main()
