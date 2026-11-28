from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import PROJECT_ROOT, iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_str

if TYPE_CHECKING:
    from pathlib import Path

BACKEND = PROJECT_ROOT / "roles/svc-stack/tasks/backend.yml"
RDBMS_DEDICATED = PROJECT_ROOT / "roles/sys-svc-rdbms/tasks/dedicated.yml"
BLUESKY_CORE = PROJECT_ROOT / "roles/web-app-bluesky/tasks/00_core.yml"
BLUESKY_STAGING = tuple(
    PROJECT_ROOT / "roles/web-app-bluesky/tasks" / name
    for name in (
        "utils/stack/stage.yml",
        "01_social_app.yml",
        "02_login_broker.yml",
        "03_pds.yml",
    )
)
BLUESKY_BRIDGE = PROJECT_ROOT / "roles/web-app-bluesky/tasks/utils/stack.yml"
SEARXNG_CORE = PROJECT_ROOT / "roles/svc-ai-searxng/tasks/00_core.yml"
REGISTRY_CACHE = PROJECT_ROOT / "roles/svc-registry-cache"
REGISTRY_CACHE_CORE = REGISTRY_CACHE / "tasks/00_core.yml"
COMPOSE_OWNER = "sys-svc-compose"
RENDER_REPLICATED = "render_replicated_templates.yml"
BOOTSTRAP_GUARD = "run_once_sys_svc_compose is not defined"
_NOTIFY = re.compile(r"^\s*notify:\s*(?:\[\s*)?['\"]?(compose-[\w-]+)", re.MULTILINE)
_PATH_ABSOLUTE = re.compile(r"path_absolute',\s*'([^']+)'")


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


def _included_file(task: dict) -> str:
    include = task.get("include_tasks", task.get("ansible.builtin.include_tasks"))
    if isinstance(include, dict):
        include = include.get("file")
    return include if isinstance(include, str) else ""


def _resolve_include(role: Path, include: str) -> Path | None:
    match = _PATH_ABSOLUTE.search(include)
    if match:
        return PROJECT_ROOT / match.group(1)
    for base in (role / "tasks", PROJECT_ROOT / "tasks"):
        if (base / include).is_file():
            return base / include
    return None


def _queues_compose_topic(role: Path, task: dict) -> bool:
    notify = task.get("notify") or []
    topics = [notify] if isinstance(notify, str) else notify
    if any(str(topic).startswith("compose-") for topic in topics):
        return True
    include = _included_file(task)
    if RENDER_REPLICATED in include:
        return True
    children = [
        child
        for section in ("block", "rescue", "always")
        for child in task.get(section) or []
    ]
    path = _resolve_include(role, include) if include else None
    if path is not None:
        children += load_yaml_str(read_text(str(path))) or []
    return any(
        isinstance(child, dict) and _queues_compose_topic(role, child)
        for child in children
    )


def _is_compose_bootstrap(task: dict) -> bool:
    include = _role_include(task)
    return (
        include.get("name") == COMPOSE_OWNER
        and include.get("tasks_from") == "00_core.yml"
        and BOOTSTRAP_GUARD in str(task.get("when"))
    )


def _bootstrap_findings(role: Path, tasks: list) -> list[str]:
    notifier = next(
        (i for i, task in enumerate(tasks) if _queues_compose_topic(role, task)),
        None,
    )
    if notifier is None:
        return []
    bootstrap = next(
        (i for i, task in enumerate(tasks) if _is_compose_bootstrap(task)),
        None,
    )
    if bootstrap is None:
        return [f"task {notifier} notifies compose without a guarded bootstrap"]
    if bootstrap > notifier:
        return [f"task {notifier} notifies compose before bootstrap {bootstrap}"]
    return []


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
                    "staging runs before the svc-stack backend, where any flush (the "
                    "container runtime's first one on a fresh host) would run "
                    "the compose handlers before ca-inject and compose.yml exist",
                )

    def test_bluesky_rebuilds_in_its_own_tasks_after_the_bridged_backend(
        self,
    ) -> None:
        tasks = load_yaml_str(read_text(str(BLUESKY_CORE)))
        self.assertTrue(BLUESKY_BRIDGE.is_file())
        self.assertEqual(
            [
                include
                for include in _role_includes(tasks)
                if include["name"] == "svc-stack"
            ],
            [],
            "the stack entry runs the backend through the bridge before "
            "00_core, and the front batch renders the fronts before both",
        )
        self.assertTrue(
            any(
                {"compose-build", "compose-up"} <= set(task.get("notify") or [])
                for task in tasks
            )
        )

    def test_bluesky_flushes_its_own_compose_handlers_after_the_rebuild(
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
        self.assertIn(BOOTSTRAP_GUARD, str(tasks[bootstrap].get("when")))

    def test_searxng_bootstraps_the_compose_host_before_it_renders(self) -> None:
        tasks = load_yaml_str(read_text(str(SEARXNG_CORE)))
        bootstrap = next(
            index
            for index, task in enumerate(tasks)
            if _role_include(task).get("name") == COMPOSE_OWNER
            and _role_include(task).get("tasks_from") == "00_core.yml"
        )
        render = next(
            index
            for index, task in enumerate(tasks)
            if RENDER_REPLICATED
            in str((task.get("ansible.builtin.include_tasks") or {}).get("file", ""))
        )
        self.assertLess(
            bootstrap,
            render,
            "the render notifies compose-up, and the next task pulls in "
            "sys-svc-container, whose unconditional flush would run the "
            "handlers before sys-svc-compose installs the compose wrapper",
        )
        self.assertIn(BOOTSTRAP_GUARD, str(tasks[bootstrap].get("when")))

    def test_registry_cache_bootstraps_the_compose_host_before_it_notifies(
        self,
    ) -> None:
        tasks = load_yaml_str(read_text(str(REGISTRY_CACHE_CORE)))
        vendor_front = next(task for task in tasks if "block" in task)
        self.assertTrue(
            _queues_compose_topic(REGISTRY_CACHE, vendor_front),
            "the vendor front notifies compose-up two include levels down",
        )
        self.assertEqual(
            _bootstrap_findings(REGISTRY_CACHE, tasks),
            [],
            "the role is the first compose consumer of the bootstrap stage, and "
            "sys-svc-container's unconditional flush would run its compose "
            "handlers before dockerd starts and before compose.yml exists",
        )

    def test_negative_control_a_missing_late_or_unguarded_bootstrap_is_reported(
        self,
    ) -> None:
        bootstrap = {
            "ansible.builtin.include_role": {
                "name": COMPOSE_OWNER,
                "tasks_from": "00_core.yml",
            },
            "when": BOOTSTRAP_GUARD,
        }
        unguarded = {key: value for key, value in bootstrap.items() if key != "when"}
        tasks = [
            task
            for task in load_yaml_str(read_text(str(REGISTRY_CACHE_CORE)))
            if not _is_compose_bootstrap(task)
        ]
        notifier = next(index for index, task in enumerate(tasks) if "block" in task)
        self.assertEqual(_bootstrap_findings(REGISTRY_CACHE, [bootstrap, *tasks]), [])
        self.assertEqual(
            _bootstrap_findings(REGISTRY_CACHE, tasks),
            [f"task {notifier} notifies compose without a guarded bootstrap"],
        )
        self.assertEqual(
            _bootstrap_findings(REGISTRY_CACHE, [*tasks, bootstrap]),
            [f"task {notifier} notifies compose before bootstrap {len(tasks)}"],
        )
        self.assertEqual(
            _bootstrap_findings(REGISTRY_CACHE, [unguarded, *tasks]),
            [f"task {notifier + 1} notifies compose without a guarded bootstrap"],
        )

    def test_the_owner_still_holds_every_compose_topic_that_is_notified(self) -> None:  # nocheck: test.text-presence -- repository-wide lint: every notified compose topic across roles has an owner handler  # fmt: skip
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
