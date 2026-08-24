import json
import os
import shutil
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stdout
from unittest.mock import patch

from cli.build import tree as tree_module


class TestFindRoles(unittest.TestCase):
    def setUp(self) -> None:
        self.roles_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.roles_dir, ignore_errors=True))

    def test_find_roles_returns_only_directories(self):
        os.makedirs(os.path.join(self.roles_dir, "role_a"))
        os.makedirs(os.path.join(self.roles_dir, "role_b"))
        with open(os.path.join(self.roles_dir, "not_a_role.txt"), "w", encoding="utf-8") as f:
            f.write("dummy")

        roles = dict(tree_module.find_roles(self.roles_dir))
        self.assertEqual(set(roles.keys()), {"role_a", "role_b"})
        self.assertTrue(all(os.path.isdir(path) for path in roles.values()))


class TestProcessRole(unittest.TestCase):
    def setUp(self) -> None:
        self.roles_dir = tempfile.mkdtemp()
        self.shadow_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.roles_dir, ignore_errors=True))
        self.addCleanup(lambda: shutil.rmtree(self.shadow_dir, ignore_errors=True))

        os.makedirs(os.path.join(self.roles_dir, "myrole"), exist_ok=True)

    def test_process_role_writes_tree_json_and_does_not_mutate_graphs(self):
        graphs = {
            "include_role_to": {"nodes": [{"id": "myrole"}], "links": []},
            "custom_key": {"value": 42},
        }

        with patch.object(tree_module, "build_mappings", return_value=graphs) as mocked_build:
            tree_module.process_role(
                role_name="myrole",
                roles_dir=self.roles_dir,
                depth=0,
                shadow_folder=self.shadow_dir,
                output="json",
                preview=False,
                verbose=False,
                no_include_role=False,
                no_import_role=False,
                no_dependencies=False,
                no_run_after=False,
            )

        mocked_build.assert_called_once()

        tree_file = os.path.join(self.shadow_dir, "myrole", "meta", "tree.json")
        self.assertTrue(os.path.exists(tree_file), "tree.json was not written")

        with open(tree_file, "r", encoding="utf-8") as f:
            written_graphs = json.load(f)

        self.assertEqual(graphs, written_graphs)
        self.assertNotIn("dependencies", written_graphs)

    def test_process_role_preview_calls_output_graph_and_does_not_write_file(self):
        graphs = {
            "graph_a": {"nodes": [{"id": "myrole"}], "links": []},
            "graph_b": {"nodes": [], "links": []},
        }

        with patch.object(tree_module, "build_mappings", return_value=graphs), patch.object(
            tree_module, "output_graph"
        ) as mocked_output:
            buf = StringIO()
            with redirect_stdout(buf):
                tree_module.process_role(
                    role_name="myrole",
                    roles_dir=self.roles_dir,
                    depth=0,
                    shadow_folder=self.shadow_dir,
                    output="json",
                    preview=True,
                    verbose=True,
                    no_include_role=False,
                    no_import_role=False,
                    no_dependencies=False,
                    no_run_after=False,
                )

        self.assertEqual(mocked_output.call_count, len(graphs))

        tree_file = os.path.join(self.shadow_dir, "myrole", "meta", "tree.json")
        self.assertFalse(os.path.exists(tree_file))


if __name__ == "__main__":
    unittest.main()
