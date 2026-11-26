"""Static contract of ``roles/web-app-keycloak/tasks/utils/directory_users.yml``."""

from __future__ import annotations

import importlib.util
import json
import re
import unittest

from jinja2 import StrictUndefined
from jinja2.nativetypes import NativeEnvironment

from utils.cache.files import PROJECT_ROOT, read_text
from utils.cache.yaml import load_yaml_any

FILTERS = PROJECT_ROOT / "roles/web-app-keycloak/filter_plugins"
TASKS = PROJECT_ROOT / "roles/web-app-keycloak/tasks"
HELPER = TASKS / "utils/directory_users.yml"
READER = TASKS / "utils/directory_users/read.yml"
LOGIN = TASKS / "utils/login.yml"
LOGIN_HELPERS = ("utils/directory_users.yml", "utils/user_attributes.yml")
AMBIENT_ID = re.compile(r"\b(application_id|entity_name)\b")
FIELDS = "id,username,email,emailVerified"
OWN_ID = "web-app-keycloak"
INCLUDE_ROLE = "ansible.builtin.include_role"


def kcadm_calls(tasks):
    for task in tasks:
        argv = (task.get("ansible.builtin.command") or {}).get("argv")
        if argv:
            yield task, argv


def walk(tasks):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        yield task
        for section in ("block", "rescue", "always"):
            yield from walk(task.get(section))


def login_helper_callers():
    for path in sorted((PROJECT_ROOT / "roles").glob("*/tasks/**/*.yml")):
        for task in walk(load_yaml_any(str(path))):
            include = task.get(INCLUDE_ROLE) or {}
            if include.get("tasks_from") in LOGIN_HELPERS:
                yield path, task


def role_filters() -> dict:
    """
    Returns:
        The filters the role's kcadm and directory_users plugins register.
    """
    filters = {}
    for name in ("kcadm", "directory_users"):
        spec = importlib.util.spec_from_file_location(
            f"keycloak_{name}_filters", str(FILTERS / f"{name}.py")
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        filters.update(module.FilterModule().filters())
    return filters


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

    def test_the_login_never_derives_keycloak_from_the_ambient_application_id(self):
        self.assertIsNone(AMBIENT_ID.search(read_text(str(LOGIN))))

    def test_the_login_helper_callers_leave_their_application_id_alone(self):
        callers = list(login_helper_callers())
        self.assertEqual(
            {task[INCLUDE_ROLE]["tasks_from"] for _, task in callers},
            set(LOGIN_HELPERS),
        )
        self.assertGreaterEqual(len(callers), 7)
        for path, task in callers:
            with self.subTest(caller=str(path.relative_to(PROJECT_ROOT))):
                self.assertEqual(task[INCLUDE_ROLE]["name"], OWN_ID)
                self.assertNotIn("application_id", task.get("vars") or {})

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

    def test_a_named_read_matches_the_username_exactly(self):  # nocheck: test.text-presence -- asserts on the parsed kcadm argv list  # fmt: skip
        named = next(argv for _, argv in self.calls if "exact=true" in argv)
        self.assertIn("username={{ keycloak_directory_username }}", named)

    def test_it_publishes_the_fact_through_the_directory_filter(self):
        fact = self.tasks[-1]["ansible.builtin.set_fact"]["keycloak_directory_users"]
        environment = NativeEnvironment(undefined=StrictUndefined)
        environment.filters.update(role_filters())
        admin = {
            "id": "6f1c-sub",
            "username": "administrator",
            "email": "admin@example.org",
            "emailVerified": True,
        }
        other = {**admin, "id": "7a2d-sub", "username": "administrator2"}
        self.assertEqual(
            environment.from_string(fact).render(
                keycloak_directory_pages={
                    "results": [{"stdout": json.dumps([admin, other])}]
                },
                keycloak_directory_named={"results": []},
                keycloak_directory_usernames=["administrator"],
            ),
            [admin],
        )


def argv_value(argv, flag):
    return argv[argv.index(flag) + 1]


if __name__ == "__main__":
    unittest.main()
