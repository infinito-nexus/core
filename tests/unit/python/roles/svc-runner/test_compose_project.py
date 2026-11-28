import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.docker.paths_utils import get_docker_paths
from utils.preflight.networks import PROJECT_LABEL, ownership_errors
from utils.roles.entity.name import entity_name
from utils.roles.mapping import (
    ROLE_FILE_META_NETWORKS,
    ROLE_FILE_TEMPL_COMPOSE,
    ROLE_FILE_VARS_MAIN,
)

ROLE = PROJECT_ROOT / "roles" / "svc-runner"
COMPOSE_ROLE = PROJECT_ROOT / "roles" / "sys-svc-compose"
SYSCTL_ROLE = PROJECT_ROOT / "roles" / "sys-sysctl"
WRAPPER = COMPOSE_ROLE / "files" / "python" / "compose.py"
COMPOSE_HANDLERS = COMPOSE_ROLE / "handlers" / "compose.yml"
INSTANCE_LOOKUP = "lookup('container', application_id, 'directories.instance')"
COMPOSE_FILE_LOOKUP = "lookup('container', application_id, 'files.compose')"
TEMPLATE_MODULES = ("template", "ansible.builtin.template", "stack_host_template")


def _load_wrapper():
    spec = spec_from_file_location("svc_runner_compose_wrapper", str(WRAPPER))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _role_tasks():
    tasks = []
    for path in sorted((ROLE / "tasks").glob("*.yml")):
        tasks.extend(load_yaml_any(str(path)) or [])
    return tasks


def _task_module(task, names):
    for name in names:
        if name in task:
            return task[name]
    return None


def _notifies(task):
    notify = task.get("notify", [])
    return [notify] if isinstance(notify, str) else list(notify)


class TestRunnerComposeProject(unittest.TestCase):
    def setUp(self):
        self.vars = load_yaml_any(str(ROLE / ROLE_FILE_VARS_MAIN))
        self.application_id = self.vars["application_id"]
        self.entity = entity_name(self.application_id)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.compositions = scratch.name.rstrip("/") + "/"
        self.instance_dir = Path(
            get_docker_paths(self.application_id, self.compositions)["directories"][
                "instance"
            ]
        )
        self.instance_dir.mkdir()

    def compose_up_handler(self):
        handlers = load_yaml_any(str(COMPOSE_HANDLERS))
        ups = [
            handler
            for handler in handlers
            if "compose up -d" in str(handler.get("ansible.builtin.shell", ""))
            and "compose-up" in handler.get("listen", [])
        ]
        self.assertEqual(len(ups), 1, ups)
        return ups[0]

    def deployed_project(self):
        handler = self.compose_up_handler()
        self.assertEqual(
            handler["args"]["chdir"].replace(" ", ""),
            "{{" + INSTANCE_LOOKUP.replace(" ", "") + "}}",
        )
        wrapper = _load_wrapper()
        captured = {}

        def build_cmd(project, project_dir, passthrough, extra_files=None):
            captured["project"] = project

        with (
            patch.object(wrapper, "build_cmd", build_cmd),
            patch.object(wrapper.Path, "cwd", lambda: self.instance_dir),
            patch.object(wrapper.sys, "argv", ["compose", "up", "-d"]),
        ):
            self.assertEqual(wrapper.main(), 0)
        return captured["project"]

    def test_stack_runs_as_the_entity_project(self):
        self.assertEqual(self.deployed_project(), self.entity)

    def test_network_of_the_stack_passes_the_preflight(self):
        subnet = load_yaml_any(str(ROLE / ROLE_FILE_META_NETWORKS))["local"]["subnet"]
        network = {
            "Name": self.entity,
            "Labels": {PROJECT_LABEL: self.deployed_project()},
            "IPAM": {"Config": [{"Subnet": subnet}]},
        }
        self.assertEqual(
            ownership_errors([network], {self.entity: [(self.application_id, subnet)]}),
            [],
        )

    def test_role_runs_no_compose_up_of_its_own(self):
        own_ups = [
            task.get("name")
            for task in _role_tasks()
            if " up " in str(task.get("ansible.builtin.shell", ""))
            or " up " in str(task.get("ansible.builtin.command", ""))
            or " up " in str(task.get("shell", ""))
            or " up " in str(task.get("command", ""))
        ]
        self.assertEqual(own_ups, [])

    def test_role_hands_the_stack_to_the_default_compose_flow(self):
        tasks = _role_tasks()
        includes = [
            index
            for index, task in enumerate(tasks)
            if (
                _task_module(task, ("include_role", "ansible.builtin.include_role"))
                or {}
            ).get("name")
            == "sys-svc-compose"
            and "tasks_from"
            not in _task_module(task, ("include_role", "ansible.builtin.include_role"))
        ]
        self.assertEqual(len(includes), 1, includes)
        flushes = [
            index
            for index, task in enumerate(tasks)
            if _task_module(task, ("meta", "ansible.builtin.meta")) == "flush_handlers"
        ]
        self.assertTrue(flushes, "no flush_handlers after the compose include")
        self.assertGreater(max(flushes), includes[0])

    def test_role_keeps_its_stack_a_compose_project_in_swarm(self):
        self.assertEqual(self.vars.get("compose_mode_force"), "compose")

    def test_every_compose_render_lands_in_the_default_instance_dir(self):
        self.assertTrue((ROLE / ROLE_FILE_TEMPL_COMPOSE).is_file())
        renders = [
            task
            for task in _role_tasks()
            if str((_task_module(task, TEMPLATE_MODULES) or {}).get("src", ""))
            == Path(ROLE_FILE_TEMPL_COMPOSE).name
        ]
        for task in renders:
            dest = _task_module(task, TEMPLATE_MODULES)["dest"]
            self.assertEqual(
                dest.replace(" ", ""),
                "{{" + COMPOSE_FILE_LOOKUP.replace(" ", "") + "}}",
                task.get("name"),
            )
            self.assertIn("compose-up", _notifies(task), task.get("name"))

    def test_runner_env_change_recreates_the_stack(self):
        writes = [
            task
            for task in _role_tasks()
            if str((_task_module(task, TEMPLATE_MODULES) or {}).get("src", ""))
            == "runner/instance_env.j2"
        ]
        self.assertEqual(len(writes), 1, writes)
        self.assertIn("compose-up", _notifies(writes[0]))

    def test_sysctl_conf_is_named_after_the_entity(self):
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        environment.filters["entity_name"] = entity_name
        owner = environment.from_string(self.vars["RUNNER_SYSCTL_OWNER"]).render(
            application_id=self.application_id
        )
        sysctl_vars = load_yaml_any(str(SYSCTL_ROLE / ROLE_FILE_VARS_MAIN))
        rendered = environment.from_string(sysctl_vars["sys_sysctl_file"]).render(
            sys_sysctl_owner=owner
        )
        self.assertEqual(rendered, f"/etc/sysctl.d/99-{self.entity}.conf")


if __name__ == "__main__":
    unittest.main()
