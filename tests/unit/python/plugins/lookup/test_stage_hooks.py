import tempfile
import unittest
from pathlib import Path

from ansible.errors import AnsibleError

from plugins.lookup.stage_hooks import LookupModule, hook_roles
from utils import PROJECT_ROOT


class TestStageHooks(unittest.TestCase):
    def test_finds_only_roles_with_that_hook_in_name_order(self):
        with tempfile.TemporaryDirectory() as td:
            roles = Path(td)
            for role, point in (
                ("b-role", "destructor"),
                ("a-role", "destructor"),
                ("c-role", "constructor"),
            ):
                hook = roles / role / "tasks" / "hooks" / f"{point}.yml"
                hook.parent.mkdir(parents=True)
                hook.write_text("---\n", encoding="utf-8")
            (roles / "d-role" / "tasks").mkdir(parents=True)
            self.assertEqual(hook_roles(roles, "destructor"), ["a-role", "b-role"])
            self.assertEqual(hook_roles(roles, "backend"), [])

    def test_repository_registrations(self):
        lookup = LookupModule()
        variables = {"playbook_dir": str(PROJECT_ROOT)}
        self.assertEqual(
            lookup.run(["constructor"], variables), ["sys-svc-wazuh-agent"]
        )
        self.assertEqual(lookup.run(["backend"], variables), ["sys-svc-wazuh-agent"])
        self.assertEqual(lookup.run(["destructor"], variables), ["web-app-wazuh"])
        self.assertEqual(
            lookup.run(["destructor_post"], variables), ["sys-svc-wazuh-agent"]
        )

    def test_rejects_anything_but_one_hook_point(self):
        with self.assertRaises(AnsibleError):
            LookupModule().run([], {"playbook_dir": str(PROJECT_ROOT)})


if __name__ == "__main__":
    unittest.main()
