import unittest
from itertools import product

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/web-app-keycloak"
EXPRESSION = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))[
    "KEYCLOAK_LDAP_USER_OBJECT_CLASSES"
]
UPDATE_ROUTINES = load_yaml_any(
    str(ROLE_DIR / "tasks/03_manager_ops/update_routines.yml")
)
EMAIL_POLICY = load_yaml_any(str(ROLE_DIR / "tasks/update/14_email_policy.yml"))
LDAP = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/12_ldap.yml"))["LDAP"]
BASE_CLASSES = "person, inetOrgPerson, nextcloudUser, ldapPublicKey, infinitoUser"


def environment() -> Environment:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    env.filters["dict2items"] = lambda mapping: [
        {"key": key, "value": value} for key, value in mapping.items()
    ]
    return env


def render(mailbox: bool) -> str:
    return (
        environment()
        .from_string(EXPRESSION)
        .render(LDAP=LDAP, KEYCLOAK_EMAIL_MAILBOX=mailbox)
        .strip()
    )


def layout_gate() -> tuple[int, str]:
    return next(
        (index, task["ansible.builtin.set_fact"]["kc_email_mailbox_layout"])
        for index, task in enumerate(EMAIL_POLICY)
        if "kc_email_mailbox_layout" in task.get("ansible.builtin.set_fact", {})
    )


def layout_block() -> tuple[int, dict]:
    return next(
        (index, task)
        for index, task in enumerate(EMAIL_POLICY)
        if any(
            child.get("ansible.builtin.include_role", {}).get("tasks_from")
            == "06_mailbox.yml"
            for child in task.get("block", [])
        )
    )


class TestLdapUserObjectClasses(unittest.TestCase):
    def test_the_external_policy_requires_the_classes_of_the_base(self):
        self.assertEqual(render(False), BASE_CLASSES)

    def test_the_mailbox_policy_also_requires_the_mailbox_class(self):
        self.assertEqual(
            render(True),
            f"{BASE_CLASSES}, infinitoMailboxUser",
        )

    def test_every_mailbox_deploy_attaches_the_class_before_the_federation_needs_it(
        self,
    ):
        includes = [task.get("include_tasks", "") for task in UPDATE_ROUTINES]
        policy = next(i for i, path in enumerate(includes) if "14_email_policy" in path)
        federation = next(
            i for i, path in enumerate(includes) if "03_ldap/shared" in path
        )
        self.assertLess(policy, federation)
        gate_index, _ = layout_gate()
        block_index, block = layout_block()
        self.assertLess(gate_index, block_index)
        self.assertEqual(block["when"], "kc_email_mailbox_layout | bool")

    def test_the_layout_applies_only_with_mailbox_and_ldap(self):
        _, gate = layout_gate()
        template = environment().from_string(gate)
        for mailbox, ldap in product((True, False), repeat=2):
            with self.subTest(mailbox=mailbox, ldap=ldap):
                self.assertEqual(
                    template.render(
                        KEYCLOAK_EMAIL_MAILBOX=mailbox, KEYCLOAK_LDAP_ENABLED=ldap
                    ),
                    str(mailbox and ldap),
                )


if __name__ == "__main__":
    unittest.main()
