from __future__ import annotations

import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

from .templates.test_realm_import_json import LDAP_PROVIDER, realm_for

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
ROUTINES = ROLE_DIR / "tasks/03_manager_ops/update_routines.yml"
BIND = ROLE_DIR / "tasks/update/03_ldap/bind.yml"
BIND_INCLUDE = "tasks/update/03_ldap/bind.yml"
SHARED_INCLUDE = "tasks/update/03_ldap/shared.yml"
REQUIRED_ACTIONS = "tasks/update/12_required_actions.yml"
FEDERATION_READS = (
    "tasks/update/14_email_policy.yml",
    "tasks/update/06_users/email/federated.yml",
    "tasks/update/06_users/email/verified.yml",
)
BIND_VARS = {
    "bindDn": "KEYCLOAK_LDAP_BIND_DN",
    "bindCredential": "KEYCLOAK_LDAP_BIND_PW",
}
MODULE = "keycloak_kcadm_update"


def include_paths(tasks: list[dict]) -> list[str]:
    """
    Args:
        tasks: the update routines, in include order.

    Returns:
        One include path per task.
    """
    return [str(task.get("include_tasks", "")) for task in tasks]


def position(tasks: list[dict], suffix: str) -> int:
    """
    Args:
        tasks: the update routines, in include order.
        suffix: the role-relative path of the included file.

    Returns:
        The index of the first matching include.
    """
    return next(
        i for i, path in enumerate(include_paths(tasks)) if path.endswith(suffix)
    )


def bind_precedes_reads(tasks: list[dict]) -> bool:
    """
    Args:
        tasks: the update routines, in include order.

    Returns:
        True when the bind include sits before every federation read.
    """
    bind = position(tasks, BIND_INCLUDE)
    reads = [
        i
        for i, path in enumerate(include_paths(tasks))
        if path.endswith(FEDERATION_READS)
    ]
    return len(reads) == len(FEDERATION_READS) and all(bind < i for i in reads)


class TestLdapBindOrder(unittest.TestCase):
    def setUp(self):
        self.tasks = load_yaml_any(str(ROUTINES))

    def test_the_bind_converges_before_every_read_through_the_federation(self):
        self.assertTrue(bind_precedes_reads(self.tasks))

    def test_a_bind_after_the_directory_trust_fails_the_check(self):
        bind = self.tasks[position(self.tasks, BIND_INCLUDE)]
        moved = [task for task in self.tasks if task is not bind] + [bind]
        self.assertFalse(bind_precedes_reads(moved))

    def test_the_required_actions_still_converge_first(self):
        self.assertLess(
            position(self.tasks, REQUIRED_ACTIONS),
            position(self.tasks, BIND_INCLUDE),
        )

    def test_the_bind_runs_under_the_gate_of_the_shared_federation(self):
        self.assertEqual(
            self.tasks[position(self.tasks, BIND_INCLUDE)]["when"],
            self.tasks[position(self.tasks, SHARED_INCLUDE)]["when"],
        )


class TestLdapBindTask(unittest.TestCase):
    def setUp(self):
        self.task = next(t for t in load_yaml_any(str(BIND)) if MODULE in t)
        self.args = self.task[MODULE]

    def test_it_updates_an_existing_component_by_id_and_never_creates_one(self):
        self.assertEqual(self.args["object_kind"], "component")
        self.assertEqual(self.args["lookup_field"], "id")
        self.assertEqual(self.args["lookup_value"], "{{ kc_ldap_bind_cmp_id }}")
        self.assertEqual(self.task["when"], "kc_ldap_bind_cmp_id | length > 0")

    def test_it_merges_only_the_bind_pair_into_the_config(self):
        self.assertEqual(self.args["merge_path"], "config")
        self.assertEqual(
            self.args["desired"],
            {"config": {key: [f"{{{{ {var} }}}}"] for key, var in BIND_VARS.items()}},
        )

    def test_it_writes_the_bind_the_realm_import_writes(self):
        bind = {var: f"rendered-{key}" for key, var in BIND_VARS.items()}
        imported = realm_for(bind)["components"][LDAP_PROVIDER][0]["config"]
        env = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        for key, values in self.args["desired"]["config"].items():
            with self.subTest(key=key):
                self.assertEqual(
                    imported[key],
                    [env.from_string(value).render(**bind) for value in values],
                )

    def test_it_masks_the_credential(self):
        self.assertEqual(self.task["no_log"], "{{ MASK_CREDENTIALS_IN_LOGS | bool }}")


if __name__ == "__main__":
    unittest.main()
