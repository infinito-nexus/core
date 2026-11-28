import unittest

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_VARS_MAIN

ROLE_DIR = PROJECT_ROOT / "roles/svc-db-openldap"
EXPRESSION = load_yaml_any(str(ROLE_DIR / ROLE_FILE_VARS_MAIN))[
    "OPENLDAP_USER_AUXILIARY_CLASSES"
]
UPDATE_TASKS = load_yaml_any(str(ROLE_DIR / "tasks/05_update.yml"))
LDAP = load_yaml_any(str(PROJECT_ROOT / "group_vars/all/12_ldap.yml"))["LDAP"]


def render(mailbox: bool) -> str:
    env = Environment(
        undefined=StrictUndefined,
        autoescape=select_autoescape(default_for_string=False),
    )
    env.filters["bool"] = bool
    env.filters["dict2items"] = lambda mapping: [
        {"key": key, "value": value} for key, value in mapping.items()
    ]
    return env.from_string(EXPRESSION).render(LDAP=LDAP, OPENLDAP_EMAIL_MAILBOX=mailbox)


class TestUserAuxiliaryClasses(unittest.TestCase):
    def test_the_external_policy_attaches_no_mailbox_class(self):
        self.assertEqual(
            render(False), "['nextcloudUser', 'ldapPublicKey', 'infinitoUser']"
        )

    def test_the_mailbox_policy_attaches_the_mailbox_class(self):
        self.assertEqual(
            render(True),
            "['nextcloudUser', 'ldapPublicKey', 'infinitoUser', 'infinitoMailboxUser']",
        )

    def test_the_update_attaches_the_policy_dependent_classes(self):
        attach = next(task for task in UPDATE_TASKS if "ldap_entries" in task)[
            "ldap_entries"
        ]["entries"]
        self.assertIn("OPENLDAP_USER_AUXILIARY_CLASSES", attach)
        self.assertNotIn("LDAP.USER.OBJECTS.AUXILIARY", attach)


if __name__ == "__main__":
    unittest.main()
