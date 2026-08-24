import importlib.util
import unittest
from unittest.mock import patch

from ansible.errors import AnsibleError

from . import PROJECT_ROOT


def _load_module(rel_path: str, name: str):
    path = PROJECT_ROOT / rel_path
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


class TestLookupDocker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module("plugins/lookup/container.py", "lookup_plugins_docker")
        cls.LookupModule = cls.mod.LookupModule

    def setUp(self):
        self.lookup = self.LookupModule()
        self.vars_ok = {"DIR_COMPOSITIONS": "/opt/compose/"}

        self.fake_paths = {
            "directories": {
                "instance": "/opt/compose/app/",
                "env": "/opt/compose/app/.env/",
                "services": "/opt/compose/app/services/",
                "volumes": "/opt/compose/app/volumes/",
                "config": "/opt/compose/app/config/",
            },
            "files": {
                "env": "/opt/compose/app/.env/app.env",
                "compose": "/opt/compose/app/compose.yml",
                "compose_override": "/opt/compose/app/compose.override.yml",
                "dockerfile": "/opt/compose/app/Dockerfile",
            },
        }

    def test_returns_full_dict_when_only_application_id(self):
        with patch.object(
            self.mod, "get_docker_paths", return_value=self.fake_paths
        ) as p:
            out = self.lookup.run(["web-app-mailu"], variables=self.vars_ok)
            self.assertEqual(out, [self.fake_paths])
            p.assert_called_once_with("web-app-mailu", "/opt/compose/")

    def test_returns_subdict_for_top_level_key(self):
        with patch.object(self.mod, "get_docker_paths", return_value=self.fake_paths):
            out = self.lookup.run(
                ["web-app-mailu", "directories"], variables=self.vars_ok
            )
            self.assertEqual(out, [self.fake_paths["directories"]])

            out = self.lookup.run(["web-app-mailu", "files"], variables=self.vars_ok)
            self.assertEqual(out, [self.fake_paths["files"]])

    def test_returns_deep_value_for_dotted_path(self):
        with patch.object(self.mod, "get_docker_paths", return_value=self.fake_paths):
            out = self.lookup.run(
                ["web-app-mailu", "directories.instance"], variables=self.vars_ok
            )
            self.assertEqual(out, ["/opt/compose/app/"])

            out = self.lookup.run(
                ["web-app-mailu", "files.env"], variables=self.vars_ok
            )
            self.assertEqual(out, ["/opt/compose/app/.env/app.env"])

    def test_invalid_path_raises(self):
        with patch.object(self.mod, "get_docker_paths", return_value=self.fake_paths):
            with self.assertRaises(AnsibleError):
                self.lookup.run(
                    ["web-app-mailu", "doesnotexist"], variables=self.vars_ok
                )

            with self.assertRaises(AnsibleError):
                self.lookup.run(
                    ["web-app-mailu", "directories.doesnotexist"],
                    variables=self.vars_ok,
                )

            with self.assertRaises(AnsibleError):
                self.lookup.run(
                    ["web-app-mailu", "directories.instance.foo"],
                    variables=self.vars_ok,
                )

    def test_missing_instances_base_var_raises(self):
        with patch.object(self.mod, "get_docker_paths", return_value=self.fake_paths):
            with self.assertRaises(AnsibleError) as ctx:
                self.lookup.run(["web-app-mailu"], variables={})
            self.assertIn("DIR_COMPOSITIONS not set", str(ctx.exception))

    def test_empty_application_id_raises(self):
        with patch.object(self.mod, "get_docker_paths", return_value=self.fake_paths):
            with self.assertRaises(AnsibleError) as ctx:
                self.lookup.run(["   "], variables=self.vars_ok)
            self.assertIn("application_id is empty", str(ctx.exception))

    def test_wrong_arity_raises(self):
        with patch.object(self.mod, "get_docker_paths", return_value=self.fake_paths):
            with self.assertRaises(AnsibleError):
                self.lookup.run([], variables=self.vars_ok)

            with self.assertRaises(AnsibleError):
                self.lookup.run(["a", "b", "c"], variables=self.vars_ok)


if __name__ == "__main__":
    unittest.main()
