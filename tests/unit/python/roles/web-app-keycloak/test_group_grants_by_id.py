import shlex
import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.kcadm_json import json_from_noisy_stdout
from utils.roles.mapping import ROLE_FILE_META_RBAC

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
TASKS = ROLE_DIR / "tasks/update"
RBAC_ROLES = load_yaml_any(str(ROLE_DIR / ROLE_FILE_META_RBAC))["roles"]
KCADM_STDOUT = (
    "[0.001s][warning][os,container] Cgroup memory controller path moved\n"
    '{\n  "id" : "4b7bea7d-cbcc-44b8-bd9e-9b31131a94db"\n}\n'
)


def shells(task_file):
    """Return the shell command templates of a task file, in task order.

    Args:
        task_file: file name below ``tasks/update``.
    """
    return [
        task["ansible.builtin.shell"] for task in load_yaml_any(str(TASKS / task_file))
    ]


def render(template, **context):
    """Render a shell command template the way the role's tasks see it.

    Args:
        template: the ``ansible.builtin.shell`` value.
        context: task variables.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["quote"] = lambda value: shlex.quote(str(value))
    env.filters["kcadm_json"] = json_from_noisy_stdout
    env.globals["lookup"] = lambda name, application_id, role: (
        f"roles/{application_id}/{role}"
    )
    return " ".join(
        env.from_string(template)
        .render(KEYCLOAK_EXEC_KCADM="kcadm", KEYCLOAK_REALM="realm", **context)
        .split()
    )


class TestGroupGrantsById(unittest.TestCase):
    def test_no_grant_names_its_group_by_path(self):
        for task_file in ("09_console_rbac.yml", "10_realm_role_grants.yml"):
            for shell in shells(task_file):
                self.assertNotIn("--gpath", shell, task_file)

    def test_console_group_is_resolved_by_its_rbac_path(self):
        resolve, _ = shells("09_console_rbac.yml")
        self.assertIn(
            "kcadm get group-by-path/roles/web-app-keycloak/user-manager -r realm",
            render(
                resolve,
                application_id="web-app-keycloak",
                item={"key": "user-manager", "value": RBAC_ROLES["user-manager"]},
            ),
        )

    def test_console_grant_targets_the_resolved_id(self):
        _, grant = shells("09_console_rbac.yml")
        auditor = RBAC_ROLES["auditor"]
        self.assertEqual(
            render(
                grant,
                KEYCLOAK_CONSOLE_ROLE_CLIENT="realm-management",
                item={
                    "item": {"key": "auditor", "value": auditor},
                    "stdout": KCADM_STDOUT,
                },
            ),
            "kcadm add-roles -r realm --gid 4b7bea7d-cbcc-44b8-bd9e-9b31131a94db"
            " --cclientid realm-management "
            + " ".join(f"--rolename {name}" for name in auditor["realm_management"]),
        )

    def test_realm_role_group_is_resolved_by_its_rbac_path(self):
        _, resolve, _ = shells("10_realm_role_grants.yml")
        self.assertIn(
            "kcadm get group-by-path/roles/web-app-opencloud/administrator -r realm",
            render(
                resolve,
                item={
                    "role": "web-app-opencloud-administrator",
                    "group_path": "/roles/web-app-opencloud/administrator",
                },
            ),
        )

    def test_realm_role_grant_targets_the_resolved_id(self):
        _, _, grant = shells("10_realm_role_grants.yml")
        self.assertEqual(
            render(
                grant,
                item={
                    "item": {"role": "web-app-opencloud-administrator"},
                    "stdout": KCADM_STDOUT,
                },
            ),
            "kcadm add-roles -r realm --gid 4b7bea7d-cbcc-44b8-bd9e-9b31131a94db"
            " --rolename web-app-opencloud-administrator",
        )


if __name__ == "__main__":
    unittest.main()
