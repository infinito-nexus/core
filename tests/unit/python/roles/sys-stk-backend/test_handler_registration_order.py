"""A role may only notify a handler topic that is already registered."""

from __future__ import annotations

import re
import unittest

from utils.cache.files import PROJECT_ROOT, iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_TASKS_MAIN

BACKEND = PROJECT_ROOT / "roles/sys-stk-backend" / ROLE_FILE_TASKS_MAIN
RDBMS_DEDICATED = PROJECT_ROOT / "roles/sys-svc-rdbms/tasks/dedicated.yml"
BLUESKY_CORE = PROJECT_ROOT / "roles/web-app-bluesky/tasks/00_core.yml"
BLUESKY_STAGING = tuple(
    PROJECT_ROOT / "roles/web-app-bluesky/tasks" / name
    for name in ("01_social_app.yml", "02_login_broker.yml", "03_pds.yml")
)
COMPOSE_OWNER = "sys-svc-compose"
_NOTIFY = re.compile(r"^\s*notify:\s*(?:\[\s*)?['\"]?(compose-[\w-]+)", re.MULTILINE)


def _role_include(task: dict) -> dict:
    for key in ("include_role", "import_role"):
        include = task.get(key) or task.get(f"ansible.builtin.{key}")
        if isinstance(include, dict):
            return include
    return {}


def _role_includes(tasks: list) -> list[dict]:
    includes = []
    for task in tasks:
        include = _role_include(task)
        if include.get("name"):
            includes.append(include)
    return includes


class TestHandlerRegistrationOrder(unittest.TestCase):
    def test_the_backend_renders_the_stack_after_every_foreign_provider(self) -> None:
        includes = _role_includes(load_yaml_str(read_text(str(BACKEND))))
        order = [include["name"] for include in includes]
        self.assertIn(COMPOSE_OWNER, order)
        render = next(
            index
            for index, include in enumerate(includes)
            if include["name"] == COMPOSE_OWNER and not include.get("tasks_from")
        )
        for provider in ("sys-svc-rdbms", "sys-svc-objstore", "sys-svc-engine"):
            with self.subTest(provider=provider):
                self.assertLess(order.index(provider), render)

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

    def test_the_notifier_registers_the_owner_before_its_first_notify(self) -> None:
        loader = _role_include(load_yaml_str(read_text(str(RDBMS_DEDICATED)))[0])
        self.assertEqual(loader.get("name"), COMPOSE_OWNER)
        self.assertEqual(loader.get("handlers_from"), "main")

    def test_bluesky_pre_compose_staging_notifies_no_compose_topic(self) -> None:
        for path in BLUESKY_STAGING:
            with self.subTest(path=path.name):
                self.assertEqual(
                    _NOTIFY.findall(read_text(str(path))),
                    [],
                    "staging runs before sys-stk-backend, where any flush (the "
                    "container runtime's first one on a fresh host) would run "
                    "the compose handlers before ca-inject and compose.yml exist",
                )

    def test_bluesky_rebuilds_after_the_backend_renders_the_stack(self) -> None:
        tasks = load_yaml_str(read_text(str(BLUESKY_CORE)))
        backend = next(
            index
            for index, task in enumerate(tasks)
            if _role_include(task).get("name") == "sys-stk-backend"
        )
        rebuild = next(
            index
            for index, task in enumerate(tasks)
            if {"compose-build", "compose-up"} <= set(task.get("notify") or [])
        )
        self.assertGreater(rebuild, backend)

    def test_bluesky_flushes_its_own_compose_handlers_before_the_front_proxy(
        self,
    ) -> None:
        tasks = load_yaml_str(read_text(str(BLUESKY_CORE)))
        rebuild = next(
            index
            for index, task in enumerate(tasks)
            if {"compose-build", "compose-up"} <= set(task.get("notify") or [])
        )
        flush = next(
            index
            for index, task in enumerate(tasks)
            if index > rebuild
            and (
                task.get("meta") == "flush_handlers"
                or task.get("ansible.builtin.meta") == "flush_handlers"
            )
        )
        proxy = next(
            index
            for index, task in enumerate(tasks)
            if _role_include(task).get("name") == "sys-stk-front-proxy"
        )
        self.assertLess(
            flush,
            proxy,
            "the front proxy pulls in svc-prx-openresty, which flushes; a "
            "compose topic still pending there is run with openresty's "
            "application_id and brings up its stack instead of this one",
        )

        loader = _role_include(tasks[flush - 1])
        self.assertEqual(loader.get("name"), COMPOSE_OWNER)
        self.assertEqual(
            loader.get("handlers_from"),
            "main",
            "the handler resolves its chdir from application_id at flush "
            "time, so the topics are re-owned here rather than left on "
            "whatever value the play happens to carry",
        )

    def test_the_notifier_bootstraps_the_compose_host_before_its_first_notify(
        self,
    ) -> None:
        tasks = load_yaml_str(read_text(str(RDBMS_DEDICATED)))
        bootstrap = next(
            index
            for index, task in enumerate(tasks)
            if _role_include(task).get("tasks_from") == "00_core.yml"
        )
        notify = next(index for index, task in enumerate(tasks) if task.get("notify"))
        self.assertLess(bootstrap, notify)
        self.assertIn(
            "run_once_sys_svc_compose is not defined", str(tasks[bootstrap].get("when"))
        )

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
