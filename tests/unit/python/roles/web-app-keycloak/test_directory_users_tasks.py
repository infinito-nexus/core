"""Static contract of ``roles/web-app-keycloak/tasks/utils/directory_users.yml``."""

from __future__ import annotations

import unittest

from utils.cache.files import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any

TASKS = PROJECT_ROOT / "roles/web-app-keycloak/tasks"
HELPER = TASKS / "utils/directory_users.yml"
READER = TASKS / "utils/directory_users/read.yml"
FIELDS = "id,username,email,emailVerified"


def kcadm_calls(tasks):
    for task in tasks:
        argv = (task.get("ansible.builtin.command") or {}).get("argv")
        if argv:
            yield task, argv


class TestDirectoryUsersHelper(unittest.TestCase):
    def setUp(self):
        self.root = load_yaml_any(str(HELPER))
        self.gate = self.root[0]
        self.login, self.read = self.gate["block"]
        self.block_vars = self.read["vars"]
        self.tasks = load_yaml_any(str(READER))
        self.calls = list(kcadm_calls(self.tasks))

    def test_it_reads_the_directory_on_the_stack_host_only(self):
        self.assertEqual(len(self.root), 1)
        self.assertEqual(self.gate["when"], "IS_STACK_HOST | bool")

    def test_it_logs_kcadm_in_through_the_role_login(self):
        self.assertEqual(
            self.login["ansible.builtin.include_tasks"],
            "{{ role_path }}/tasks/utils/login.yml",
        )

    def test_it_queries_through_the_reader_after_the_login(self):
        self.assertEqual(
            self.read["ansible.builtin.include_tasks"],
            "{{ role_path }}/tasks/utils/directory_users/read.yml",
        )

    def test_every_kcadm_call_is_a_read_on_the_users_endpoint(self):
        self.assertEqual(len(self.calls), 3)
        for _, argv in self.calls:
            with self.subTest(argv=argv):
                self.assertEqual(argv[:3], ["container", "exec", "-i"])
                self.assertEqual(argv[4], "{{ KEYCLOAK_KCADM }}")
                self.assertEqual(argv[5], "get")
                self.assertIn(argv[6], ("users", "users/count"))

    def test_every_kcadm_call_runs_on_the_keycloak_node_and_changes_nothing(self):
        for task, _ in self.calls:
            with self.subTest(task=task["name"]):
                self.assertEqual(task["delegate_to"], "{{ KEYCLOAK_HOST_NODE }}")
                self.assertIs(task["changed_when"], False)

    def test_every_listing_asks_for_the_fields_the_filter_needs(self):
        self.assertEqual(self.block_vars["keycloak_directory_fields"], FIELDS)
        for _, argv in self.calls:
            if argv[6] == "users":
                self.assertEqual(
                    argv[argv.index("--fields") + 1], "{{ keycloak_directory_fields }}"
                )

    def test_the_all_users_read_pages_with_offset_and_limit(self):
        pages = next(argv for _, argv in self.calls if "--offset" in argv)
        self.assertEqual(argv_value(pages, "--limit"), "{{ keycloak_directory_page }}")
        self.assertEqual(
            argv_value(pages, "--offset"), "{{ keycloak_directory_offset }}"
        )

    def test_a_named_read_matches_the_username_exactly(self):
        named = next(argv for _, argv in self.calls if "exact=true" in argv)
        self.assertIn("username={{ keycloak_directory_username }}", named)

    def test_it_publishes_the_fact_through_the_directory_filter(self):
        fact = self.tasks[-1]["ansible.builtin.set_fact"]["keycloak_directory_users"]
        self.assertIn("kc_directory_users(keycloak_directory_usernames)", fact)


def argv_value(argv, flag):
    return argv[argv.index(flag) + 1]


if __name__ == "__main__":
    unittest.main()
