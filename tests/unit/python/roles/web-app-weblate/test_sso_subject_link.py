"""Weblate links an SSO login by the Keycloak subject, never by e-mail."""

from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

ROLE = PROJECT_ROOT / "roles" / "web-app-weblate"
OVERRIDE_TARGET = "/app/data/settings-override.py"
SSO_FLAG = "{{ lookup('config', 'web-app-weblate', 'services.weblate.login.method.sso.enabled') | bool }}"


class WeblateSubjectLinkTests(unittest.TestCase):
    def setUp(self):
        self.volumes = load_yaml_any(str(ROLE / "meta" / "volumes.yml"))
        self.core = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"))
        self.token = load_yaml_any(str(ROLE / "tasks" / "utils" / "token.yml"))
        self.vars = load_yaml_any(str(ROLE / "vars" / "main.yml"))

    def test_every_service_reads_the_override_where_upstream_looks_for_it(self):
        override = self.volumes["settings-override"]
        self.assertEqual(override["type"], "config")
        self.assertTrue(override["source"].endswith("'settings-override.py'] | path_join }}"))
        self.assertEqual(
            {(mount["service"], mount["target"], mount["when"]) for mount in override["mounts"]},
            {(service, OVERRIDE_TARGET, SSO_FLAG) for service in ("weblate", "beat", "worker")},
        )

    def test_the_override_is_staged_before_the_first_compose_up(self):
        stack = next(i for i, task in enumerate(self.core) if task.get("include_role", {}).get("name") == "sys-stk-full")
        self.assertIs(self.core[stack]["vars"]["compose_handlers_flush"], False)
        stage = next(i for i, task in enumerate(self.core) if "stack_host_copy" in task)
        flush = next(i for i, task in enumerate(self.core) if task.get("meta") == "flush_handlers")
        self.assertLess(stack, stage)
        self.assertLess(stage, flush)
        copy = self.core[stage]
        self.assertEqual(copy["stack_host_copy"]["src"], "python/settings_override.py")
        self.assertEqual(copy["stack_host_copy"]["dest"], "{{ WEBLATE_SETTINGS_OVERRIDE_FILE }}")
        self.assertEqual(copy["notify"], "compose-up")
        self.assertEqual(copy["when"], "WEBLATE_OIDC_ENABLED | bool")

    def test_the_admin_subject_comes_from_the_keycloak_directory_helper(self):
        lookup = next(task for task in self.token if "ansible.builtin.include_role" in task)
        self.assertEqual(
            lookup["ansible.builtin.include_role"],
            {"name": "web-app-keycloak", "tasks_from": "utils/directory_users.yml"},
        )
        self.assertEqual(lookup["vars"]["application_id"], "web-app-keycloak")
        self.assertEqual(lookup["when"], "WEBLATE_OIDC_ENABLED | bool")

    def test_the_adoption_receives_the_backend_and_the_subject(self):
        adopt = next(task for task in self.token if "adopt_admin.py" in str(task.get("ansible.builtin.shell")))
        cmd = adopt["ansible.builtin.shell"]["cmd"]
        self.assertIn("-e WEBLATE_OIDC_BACKEND -e WEBLATE_ADMIN_OIDC_UID", cmd)
        self.assertEqual(adopt["environment"]["WEBLATE_OIDC_BACKEND"], "{{ WEBLATE_OIDC_BACKEND }}")
        self.assertEqual(
            adopt["environment"]["WEBLATE_ADMIN_OIDC_UID"],
            "{{ (keycloak_directory_users | first).id if (WEBLATE_OIDC_ENABLED | bool) else '' }}",
        )

    def test_the_backend_is_social_cores_generic_oidc(self):
        self.assertEqual(self.vars["WEBLATE_OIDC_BACKEND"], "oidc")


if __name__ == "__main__":
    unittest.main()
