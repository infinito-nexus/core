from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
ROUTINES = load_yaml_any(str(ROLE_DIR / "tasks/03_manager_ops/update_routines.yml"))
ROUTINE = ROLE_DIR / "tasks/update/17_organizations.yml"


class TestRoutine(unittest.TestCase):
    def test_the_routine_runs_only_while_organizations_are_on(self) -> None:
        include = next(
            task
            for task in ROUTINES
            if str(task.get("include_tasks", "")).endswith("17_organizations.yml")
        )
        self.assertEqual(include["when"], "KEYCLOAK_ORGANIZATIONS_ENABLED | bool")
        self.assertTrue(ROUTINE.is_file())

    def test_the_routine_runs_the_script_with_the_role_values_and_no_secret(
        self,
    ) -> None:
        run, fail = load_yaml_any(str(ROUTINE))
        params = run["vars"]
        self.assertEqual(params["rest_script"], "realm/organizations.py")
        self.assertEqual(
            params["rest_script_env"],
            {
                "KC_SERVICE_ACCOUNTS": "{{ KEYCLOAK_SERVICE_ACCOUNT_ROLES | to_json }}",
                "KC_ROLE_CLIENT": "{{ KEYCLOAK_CONSOLE_ROLE_CLIENT }}",
                "KC_ORGANIZATION_FLOW": "{{ KEYCLOAK_ORGANIZATION_FLOW }}",
                "KC_ORGANIZATION_REQUIREMENT": "{{ KEYCLOAK_ORGANIZATION_EXECUTION }}",
            },
        )
        self.assertEqual(fail["when"], "kc_organizations.rc != 0")
        self.assertTrue((ROLE_DIR / "files/python" / params["rest_script"]).is_file())


if __name__ == "__main__":
    unittest.main()
