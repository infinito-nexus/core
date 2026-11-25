import unittest

from utils.cache import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/svc-db-openldap/tasks"
USERS = load_yaml_any(str(TASKS / "04_users.yml"))
RENAMES = load_yaml_any(str(TASKS / "_user_renames.yml"))
RENAMES_FILE = "_user_renames.yml"
MOVE = "ldap_user_rdn"
SEARCH = "community.general.ldap_search"
INCLUDE = "ansible.builtin.include_tasks"


def _include_file(task):
    include = task.get(INCLUDE)
    return include.get("file") if isinstance(include, dict) else include


def _includes():
    return [
        index for index, task in enumerate(USERS) if _include_file(task) == RENAMES_FILE
    ]


def _entries(state):
    return next(
        index
        for index, task in enumerate(USERS)
        if task.get("ldap_entries", {}).get("state") == state
    )


def _index(tasks, module):
    return next(index for index, task in enumerate(tasks) if module in task)


def _search(register):
    return next(
        index
        for index, task in enumerate(RENAMES)
        if SEARCH in task and task.get("register") == register
    )


class TestUserRenameTasks(unittest.TestCase):
    def test_entries_move_before_any_user_entry_is_created(self):
        self.assertLess(_includes()[0], _entries("create"))

    def test_group_values_are_repointed_again_once_the_entries_exist(self):
        self.assertEqual(len(_includes()), 2)
        self.assertLess(_entries("create"), _includes()[1])
        self.assertLess(_includes()[1], _index(USERS, "ldap_passwords"))

    def test_both_passes_run_on_the_stack_host(self):
        for index in _includes():
            with self.subTest(index=index):
                self.assertEqual(
                    USERS[index][INCLUDE]["apply"],
                    {"run_once": True, "delegate_to": "{{ STACK_HOST }}"},
                )

    def test_the_single_login_is_enforced_after_the_last_move(self):
        exact = _entries("exact")
        self.assertLess(_includes()[1], exact)
        self.assertIn(
            "openldap_user_login_entries", USERS[exact]["ldap_entries"]["entries"]
        )

    def test_the_plan_reads_the_inventory_and_both_searches_gathered_before_it(self):
        renames = RENAMES[_index(RENAMES, MOVE)][MOVE]["renames"]
        for register in ("openldap_users_named", "openldap_member_groups"):
            with self.subTest(register=register):
                self.assertLess(_search(register), _index(RENAMES, MOVE))
                self.assertIn(f"{register}.results", renames)
        self.assertIn("OPENLDAP_USERS | openldap_user_renames(", renames)
        self.assertIn("LDAP.USER.OBJECTS.STRUCTURAL", renames)

    def test_the_entry_search_reads_the_markers_the_plan_checks(self):
        attrs = RENAMES[_search("openldap_users_named")][SEARCH]["attrs"]
        for attribute in ("objectClass", "homeDirectory"):
            with self.subTest(attribute=attribute):
                self.assertIn(attribute, attrs)


if __name__ == "__main__":
    unittest.main()
