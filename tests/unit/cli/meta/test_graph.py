import shutil
import tempfile
import unittest
from pathlib import Path

from cli.build import graph
from utils.cache.yaml import dump_yaml
from utils.roles.mapping import ROLE_FILE_META_MAIN, ROLE_FILE_TASKS_MAIN


class TestGraphLogic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.role_name = "role_a"
        self.role_path = str(Path(self.temp_dir) / self.role_name)
        Path(str(Path(self.role_path) / "meta")).mkdir(parents=True)
        Path(str(Path(self.role_path) / "tasks")).mkdir(parents=True)

        # Write meta/main.yml
        dump_yaml(
            str(Path(self.role_path) / ROLE_FILE_META_MAIN),
            {
                "galaxy_info": {"author": "tester", "run_after": []},
                "dependencies": [],
            },
        )

        # Write tasks/main.yml
        dump_yaml(
            str(Path(self.role_path) / ROLE_FILE_TASKS_MAIN),
            [
                {"include_role": "some_other_role"},
                {"import_role": {"name": "another_role"}},
            ],
        )

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    def test_load_meta_returns_dict(self):
        meta_path = graph.find_role_meta(self.temp_dir, self.role_name)
        meta = graph.load_meta(meta_path)
        self.assertIsInstance(meta, dict)
        self.assertIn("galaxy_info", meta)

    def test_load_tasks_include_role(self):
        task_path = graph.find_role_tasks(self.temp_dir, self.role_name)
        includes = graph.load_tasks(task_path, "include_role")
        self.assertIn("some_other_role", includes)

    def test_build_mappings_structure(self):
        result = graph.build_mappings(self.role_name, self.temp_dir, max_depth=1)
        self.assertIsInstance(result, dict)
        for key in graph.ALL_KEYS:
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
