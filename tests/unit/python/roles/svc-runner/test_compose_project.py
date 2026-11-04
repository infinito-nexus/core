import shlex
import tempfile
import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from unittest.mock import patch

from jinja2 import Environment, StrictUndefined, select_autoescape

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.networks.ownership import PROJECT_LABEL, ownership_errors
from utils.roles.entity.name import entity_name

ROLE = PROJECT_ROOT / "roles" / "svc-runner"
WRAPPER = PROJECT_ROOT / "roles" / "sys-svc-compose" / "files" / "python" / "compose.py"


def _load_wrapper():
    spec = spec_from_file_location("svc_runner_compose_wrapper", str(WRAPPER))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestRunnerComposeProject(unittest.TestCase):
    def setUp(self):
        self.application_id = load_yaml_any(str(ROLE / "vars" / "main.yml"))[
            "application_id"
        ]
        self.entity = entity_name(self.application_id)
        configured = load_yaml_any(str(ROLE / "meta" / "services.yml"))["runner"][
            "install_dir"
        ]
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.install_dir = Path(scratch.name) / Path(configured).name
        self.install_dir.mkdir()

    def deploy_argv(self):
        tasks = load_yaml_any(str(ROLE / "tasks" / "00_core.yml"))
        shells = [
            str(task["ansible.builtin.shell"])
            for task in tasks
            if " up " in str(task.get("ansible.builtin.shell", ""))
        ]
        self.assertEqual(len(shells), 1, shells)
        environment = Environment(
            undefined=StrictUndefined,
            autoescape=select_autoescape(default_for_string=False),
        )
        environment.filters["entity_name"] = entity_name
        rendered = environment.from_string(shells[0]).render(
            application_id=self.application_id,
            RUNNER_INSTALL_DIR=str(self.install_dir),
        )
        lines = [
            line
            for line in rendered.splitlines()
            if line.strip().startswith("compose ")
        ]
        self.assertEqual(len(lines), 1, rendered)
        return shlex.split(lines[0])

    def deployed_project(self):
        wrapper = _load_wrapper()
        captured = {}

        def build_cmd(project, project_dir, passthrough, extra_files=None):
            captured["project"] = project

        with (
            patch.object(wrapper, "build_cmd", build_cmd),
            patch.object(wrapper.sys, "argv", self.deploy_argv()),
        ):
            self.assertEqual(wrapper.main(), 0)
        return captured["project"]

    def test_stack_runs_as_the_entity_project(self):
        self.assertEqual(self.deployed_project(), self.entity)

    def test_network_of_the_stack_passes_the_preflight(self):
        subnet = load_yaml_any(str(ROLE / "meta" / "networks.yml"))["local"]["subnet"]
        network = {
            "Name": self.entity,
            "Labels": {PROJECT_LABEL: self.deployed_project()},
            "IPAM": {"Config": [{"Subnet": subnet}]},
        }
        self.assertEqual(
            ownership_errors([network], {self.entity: [(self.application_id, subnet)]}),
            [],
        )


if __name__ == "__main__":
    unittest.main()
