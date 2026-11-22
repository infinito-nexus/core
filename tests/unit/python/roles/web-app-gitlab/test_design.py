import unittest

from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

DESIGN = PROJECT_ROOT / "roles" / "web-app-gitlab" / "tasks" / "utils" / "design.yml"


class TestDesign(unittest.TestCase):
    def test_the_logo_read_runs_once_on_the_stack_host(self) -> None:
        block = load_yaml_any(str(DESIGN))[0]["block"]
        read = next(task for task in block if "ansible.builtin.slurp" in task)
        self.assertEqual(
            (read.get("delegate_to"), read.get("run_once")),
            ("{{ STACK_HOST }}", True),
            "design_assets renders the logo set only where IS_STACK_HOST holds, so a swarm worker that slurps it finds no file",
        )


if __name__ == "__main__":
    unittest.main()
