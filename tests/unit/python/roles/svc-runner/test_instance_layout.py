import importlib
import posixpath
import re
import unittest

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any, load_yaml_str
from utils.roles.mapping import (
    ROLE_FILE_DEFAULTS_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

_render = importlib.import_module("tests.unit.python.roles.svc-runner._render")
_environment = _render.environment
_condition = _render.condition

ROLE = _render.ROLE
COMPOSE_ROLE = PROJECT_ROOT / "roles" / "sys-svc-compose"
SYSCTL_ROLE = PROJECT_ROOT / "roles" / "sys-sysctl"
NODE_TASKS = "05_node.yml"
LEGACY_SYSCTL_CONF = "/etc/sysctl.d/99-github-runner.conf"
IDENTIFIER = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
INCLUDE_MODULES = ("include_role", "ansible.builtin.include_role")
INCLUDE_TASKS_MODULES = ("include_tasks", "ansible.builtin.include_tasks")
FLUSH_MODULES = ("meta", "ansible.builtin.meta")
FILE_MODULES = ("file", "ansible.builtin.file")
COPY_MODULES = ("copy", "ansible.builtin.copy")
DEBUG_MODULES = ("debug", "ansible.builtin.debug")
TEMPLATE_MODULES = ("template", "ansible.builtin.template")


def _tasks(name):
    return load_yaml_any(str(ROLE / "tasks" / name)) or []


def _module(task, names):
    for name in names:
        if name in task:
            return task[name]
    return None


def _notifies(task):
    notify = task.get("notify", [])
    return [notify] if isinstance(notify, str) else list(notify)


def _strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)
    elif isinstance(node, str):
        yield node


class _Changed:
    def __init__(self, changed):
        self.changed = changed


class TestRunnerInstanceLayout(unittest.TestCase):
    def setUp(self):
        self.vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.install_dir = load_yaml_any(str(ROLE / ROLE_FILE_META_SERVICES))["runner"][
            "install_dir"
        ]

    def core_indexes(self):
        tasks = _tasks("00_core.yml")
        compose = [
            index
            for index, task in enumerate(tasks)
            if (_module(task, INCLUDE_MODULES) or {}).get("name") == "sys-svc-compose"
        ]
        node = [
            index
            for index, task in enumerate(tasks)
            if _module(task, INCLUDE_TASKS_MODULES) == NODE_TASKS
        ]
        flushes = [
            index
            for index, task in enumerate(tasks)
            if _module(task, FLUSH_MODULES) == "flush_handlers"
        ]
        return tasks, compose, node, flushes

    def test_node_prep_runs_off_the_stack_host_before_the_flush(self):
        tasks, compose, node, flushes = self.core_indexes()
        self.assertEqual(len(compose), 1, compose)
        self.assertEqual(len(node), 1, node)
        self.assertTrue(flushes)
        self.assertLess(compose[0], node[0])
        self.assertLess(node[0], max(flushes))
        when = tasks[node[0]]["when"]
        self.assertFalse(_condition(when, IS_STACK_HOST=True))
        self.assertTrue(_condition(when, IS_STACK_HOST=False))

    def test_role_tasks_read_no_variable_private_to_the_compose_role(self):
        private = set(load_yaml_any(str(COMPOSE_ROLE / ROLE_FILE_VARS_MAIN))) | set(
            load_yaml_any(str(COMPOSE_ROLE / ROLE_FILE_DEFAULTS_MAIN))
        )
        own = set(self.vars) | set(load_yaml_any(str(ROLE / ROLE_FILE_DEFAULTS_MAIN)))
        leaks = sorted(
            {
                (path.name, name)
                for path in (ROLE / "tasks").glob("*.yml")
                for value in _strings(load_yaml_any(str(path)) or [])
                for name in IDENTIFIER.findall(value)
                if name in private - own
            }
        )
        self.assertEqual(leaks, [])

    def test_pending_marker_is_the_one_the_compose_handlers_clear(self):
        compose_vars = load_yaml_any(str(COMPOSE_ROLE / ROLE_FILE_VARS_MAIN))
        self.assertEqual(
            self.vars["RUNNER_COMPOSE_UP_PENDING_MARKER"],
            compose_vars["COMPOSE_UP_PENDING_MARKER"],
        )

    def test_node_render_leaves_its_compose_up_pending_until_it_succeeds(self):
        tasks = _tasks(NODE_TASKS)
        renders = [
            task
            for task in tasks
            if (_module(task, TEMPLATE_MODULES) or {}).get("src")
            == posixpath.basename(ROLE_FILE_TEMPL_COMPOSE)
        ]
        self.assertEqual(len(renders), 1, renders)
        registered = renders[0]["register"]
        markers = [
            task
            for task in tasks
            if (_module(task, COPY_MODULES) or {}).get("dest", "").replace(" ", "")
            == "{{RUNNER_COMPOSE_UP_PENDING_MARKER}}"
        ]
        self.assertEqual(len(markers), 1, markers)
        self.assertTrue(_condition(markers[0]["when"], **{registered: _Changed(True)}))
        self.assertFalse(
            _condition(markers[0]["when"], **{registered: _Changed(False)})
        )

    def test_node_start_condition_holds_without_a_probe(self):
        starts = [
            task
            for task in _tasks(NODE_TASKS)
            if _module(task, DEBUG_MODULES) is not None
            and "compose-up" in _notifies(task)
        ]
        self.assertEqual(len(starts), 1, starts)
        when = starts[0]["when"]
        cases = [
            ({"pending": False, "running": None}, False),
            ({"pending": False, "running": {"stdout": ""}}, True),
            ({"pending": False, "running": {"stdout": "abc123\n"}}, False),
            ({"pending": True, "running": {"stdout": "abc123"}}, True),
            ({"pending": True, "running": None}, True),
        ]
        for probe, expected in cases:
            with self.subTest(probe=probe):
                self.assertEqual(
                    _condition(when, _runner_node_instance=probe), expected
                )

    def test_legacy_layout_is_removed_after_the_new_stack_is_up(self):
        tasks, _compose, _node, flushes = self.core_indexes()
        removals = [
            (index, task)
            for index, task in enumerate(tasks)
            if (_module(task, FILE_MODULES) or {}).get("state") == "absent"
            and "loop" in task
            and any("compose.yml" in item for item in task["loop"])
        ]
        self.assertEqual(len(removals), 1, removals)
        index, task = removals[0]
        self.assertGreater(index, max(flushes))
        environment = _environment()
        removed = {
            environment.from_string(item).render(RUNNER_INSTALL_DIR=self.install_dir)
            for item in task["loop"]
        }
        self.assertEqual(
            removed,
            {
                posixpath.join(self.install_dir, "compose.yml"),
                posixpath.join(self.install_dir, "build"),
                LEGACY_SYSCTL_CONF,
            },
        )
        owner = environment.from_string(self.vars["RUNNER_SYSCTL_OWNER"]).render(
            application_id=self.vars["application_id"]
        )
        sysctl_vars = load_yaml_any(str(SYSCTL_ROLE / ROLE_FILE_VARS_MAIN))
        live_sysctl = environment.from_string(sysctl_vars["sys_sysctl_file"]).render(
            sys_sysctl_owner=owner
        )
        self.assertNotIn(live_sysctl, removed)


class TestRunnerComposeRender(unittest.TestCase):
    def render(self, swarm):
        return load_yaml_str(
            _render.render(_render.COMPOSE, _render.flavor_of({}), swarm=swarm)
        )

    def test_compose_mode_builds_the_runner_image_from_the_instance_dir(self):
        services = self.render(swarm=False)["services"]
        builder = services["runner-1"]
        self.assertEqual(builder["build"]["context"], ".")
        self.assertEqual(builder["build"]["dockerfile"], "Dockerfile")
        self.assertEqual(
            builder["build"]["args"],
            {
                "RUNNER_BASE_IMAGE": "ubuntu:26.04",
                "RUNNER_UID": "900",
                "RUNNER_GID": "900",
                "RUNNER_USER": _render.runner_account()["username"],
            },
        )
        self.assertEqual(builder["pull_policy"], "never")
        self.assertEqual(builder["image"], "infinito-runner:latest")
        self.assertNotIn("build", services["runner-2"])
        self.assertEqual(services["runner-2"]["image"], builder["image"])

    def test_swarm_mode_runs_the_registry_image_without_a_build(self):
        services = self.render(swarm=True)["services"]
        for name, service in services.items():
            with self.subTest(service=name):
                self.assertNotIn("build", service)
                self.assertNotIn("pull_policy", service)
                self.assertEqual(
                    service["image"], "manager:5000/infinito-runner:latest"
                )
                self.assertEqual(service["container_name"], name)


if __name__ == "__main__":
    unittest.main()
