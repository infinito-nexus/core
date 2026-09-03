"""A role may only notify a handler topic that is already registered."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

BACKEND = PROJECT_ROOT / "roles/sys-stk-backend" / ROLE_FILE_TASKS_MAIN
COMPOSE_OWNER = "sys-svc-compose"
_NOTIFY = re.compile(r"^\s*notify:\s*(?:\[\s*)?['\"]?(compose-[\w-]+)", re.MULTILINE)


def _role_include(task: dict) -> dict:
    for key in ("include_role", "import_role"):
        include = task.get(key) or task.get(f"ansible.builtin.{key}")
        if isinstance(include, dict):
            return include
    return {}


def _included_roles(tasks: list) -> list[str]:
    names = []
    for task in tasks:
        include = _role_include(task)
        if include.get("name"):
            names.append(include["name"])
    return names


class TestHandlerRegistrationOrder(unittest.TestCase):
    def test_the_backend_loads_the_handler_owner_before_any_other_role(self) -> None:
        order = _included_roles(load_yaml_str(read_text(str(BACKEND))))
        self.assertIn(COMPOSE_OWNER, order)
        self.assertEqual(order[0], COMPOSE_OWNER)

    def test_the_owner_is_reloaded_directly_before_the_flush(self) -> None:
        tasks = load_yaml_str(read_text(str(BACKEND)))
        flush = next(
            index
            for index, task in enumerate(tasks)
            if task.get("meta") == "flush_handlers"
            or task.get("ansible.builtin.meta") == "flush_handlers"
        )
        previous = tasks[flush - 1]
        loader = _role_include(previous)
        self.assertEqual(loader.get("name"), COMPOSE_OWNER)
        self.assertEqual(loader.get("handlers_from"), "main")

    def test_the_owner_still_holds_every_compose_topic_that_is_notified(self) -> None:
        owner = ""
        for path, content in iter_project_files_with_content(
            extensions=(".yml",), exclude_tests=True
        ):
            if f"roles/{COMPOSE_OWNER}/handlers/" in path:
                owner += content
        notified = set()
        for path, content in iter_project_files_with_content(
            extensions=(".yml",), exclude_tests=True
        ):
            if "/roles/" in path:
                notified.update(_NOTIFY.findall(content))
        self.assertTrue(notified)
        for topic in sorted(notified):
            with self.subTest(topic=topic):
                self.assertIn(topic, owner)


if __name__ == "__main__":
    unittest.main()
