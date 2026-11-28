import unittest
from importlib.util import module_from_spec, spec_from_file_location

from . import PROJECT_ROOT

MODULE = (
    PROJECT_ROOT
    / "roles"
    / "sys-svc-app-control"
    / "files"
    / "python"
    / "app_control_argv.py"
)


def load_module():
    spec = spec_from_file_location("app_control_argv", str(MODULE))
    module = module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


REGISTRY = {
    "instance": "/opt/compose/wiki",
    "project": "wiki",
    "stack_files": ["/opt/compose/wiki/compose.yml", "/opt/compose/wiki/override.yml"],
}


class ArgvTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_module()

    def test_compose_argv_runs_the_wrapper_in_the_instance(self):
        self.assertEqual(
            self.mod.compose_argv(
                {"compose": "/usr/bin/compose"}, REGISTRY, "up", "-d"
            ),
            [
                "/usr/bin/compose",
                "--chdir",
                "/opt/compose/wiki",
                "--project",
                "wiki",
                "up",
                "-d",
            ],
        )

    def test_stack_services_argv_lists_the_project_services_by_name(self):
        self.assertEqual(
            self.mod.stack_services_argv(REGISTRY),
            ["docker", "stack", "services", "--format", "{{.Name}}", "wiki"],
        )

    def test_scale_to_zero_argv_names_every_service_once(self):
        self.assertEqual(
            self.mod.scale_to_zero_argv(["wiki_app", "wiki_db"]),
            [
                "docker",
                "service",
                "scale",
                "--detach=false",
                "wiki_app=0",
                "wiki_db=0",
            ],
        )

    def test_stack_deploy_argv_passes_every_stack_file_in_order(self):
        self.assertEqual(
            self.mod.stack_deploy_argv(REGISTRY),
            [
                "docker",
                "stack",
                "deploy",
                "--compose-file",
                "/opt/compose/wiki/compose.yml",
                "--compose-file",
                "/opt/compose/wiki/override.yml",
                "--resolve-image",
                "never",
                "--prune",
                "--with-registry-auth",
                "wiki",
            ],
        )


if __name__ == "__main__":
    unittest.main()
