import os
import json
import shutil
import tempfile
import unittest
from io import StringIO
from contextlib import redirect_stdout

from cli.build.graph import (
    load_meta,
    load_tasks,
    build_mappings,
    output_graph,
    ALL_KEYS,
)


class TestGraphHelpers(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.tmpdir, ignore_errors=True))

    def _write_file(self, rel_path: str, content: str) -> str:
        path = os.path.join(self.tmpdir, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def test_load_meta_parses_run_after_and_dependencies(self):
        meta_path = self._write_file(
            "roles/role_a/meta/main.yml",
            """
galaxy_info:
  author: Test Author
dependencies:
  - role_d
  - role_e
""",
        )
        # Per req-010 run_after lives in meta/services.yml under the role's
        # primary entity; for "role_a" (no category prefix) the entity name
        # is the role name itself.
        self._write_file(
            "roles/role_a/meta/services.yml",
            """
role_a:
  run_after:
    - role_b
    - role_c
""",
        )

        meta = load_meta(meta_path)

        self.assertIn("galaxy_info", meta)
        self.assertEqual(meta["galaxy_info"]["author"], "Test Author")
        self.assertEqual(meta["run_after"], ["role_b", "role_c"])
        self.assertEqual(meta["dependencies"], ["role_d", "role_e"])

    def test_load_tasks_filters_out_jinja_and_reads_names(self):
        tasks_path = self._write_file(
            "roles/role_a/tasks/main.yml",
            """
- name: include plain file
  include_tasks: "subtasks.yml"

- name: include with dict
  include_tasks:
    name: "other.yml"

- name: include jinja, should be ignored
  include_tasks: "{{ dynamic_file }}"

- name: import plain file
  import_tasks: "legacy.yml"

- name: import with dict
  import_tasks:
    name: "more.yml"

- name: import jinja, should be ignored
  import_tasks: "{{ legacy_file }}"
""",
        )

        include_files = load_tasks(tasks_path, "include_tasks")
        import_files = load_tasks(tasks_path, "import_tasks")

        self.assertEqual(sorted(include_files), ["other.yml", "subtasks.yml"])
        self.assertEqual(sorted(import_files), ["legacy.yml", "more.yml"])


class TestBuildMappings(unittest.TestCase):
    def setUp(self) -> None:
        self.roles_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.roles_dir, ignore_errors=True))

    def _write_file(self, rel_path: str, content: str) -> str:
        path = os.path.join(self.roles_dir, rel_path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def _create_minimal_role(self, name: str, with_meta: bool = False) -> None:
        os.makedirs(os.path.join(self.roles_dir, name), exist_ok=True)
        if with_meta:
            self._write_file(
                f"{name}/meta/main.yml",
                """
galaxy_info:
  author: Minimal
""",
            )

    def test_build_mappings_collects_all_dependency_types(self):
        # Create roles directory structure
        self._create_minimal_role("role_b")
        self._create_minimal_role("role_c")
        self._create_minimal_role("role_d")
        self._create_minimal_role("role_e")

        # Role A with meta (dependencies); run_after now lives in services.yml
        self._write_file(
            "role_a/meta/main.yml",
            """
galaxy_info:
  author: Role A Author
dependencies:
  - role_c
""",
        )
        self._write_file(
            "role_a/meta/services.yml",
            """
role_a:
  run_after:
    - role_b
""",
        )

        # Role A tasks with include_role, import_role, include_tasks, import_tasks
        self._write_file(
            "role_a/tasks/main.yml",
            """
- name: use docker style role
  include_role:
    name: role_d

- name: use import role
  import_role:
    name: role_e

- name: include static tasks file
  include_tasks: "subtasks.yml"

- name: import static tasks file
  import_tasks:
    name: "legacy.yml"
""",
        )

        # Dummy tasks/meta for other roles not required, but create dirs so they
        # are recognized as roles.
        self._create_minimal_role("role_a")  # dirs already exist but harmless

        graphs = build_mappings("role_a", self.roles_dir, max_depth=2)

        # Ensure we got all expected graph keys
        for key in ALL_KEYS:
            self.assertIn(key, graphs, msg=f"Missing graph key {key!r} in result")

        # Helper to find links in a graph
        def links_of(key: str):
            return graphs[key]["links"]

        # run_after_to: role_a -> role_b
        run_after_links = links_of("run_after_to")
        self.assertIn(
            {"source": "role_a", "target": "role_b", "type": "run_after"},
            run_after_links,
        )

        # dependencies_to: role_a -> role_c
        dep_links = links_of("dependencies_to")
        self.assertIn(
            {"source": "role_a", "target": "role_c", "type": "dependencies"},
            dep_links,
        )

        # include_role_to: role_a -> role_d
        inc_role_links = links_of("include_role_to")
        self.assertIn(
            {"source": "role_a", "target": "role_d", "type": "include_role"},
            inc_role_links,
        )

        # import_role_to: role_a -> role_e
        imp_role_links = links_of("import_role_to")
        self.assertIn(
            {"source": "role_a", "target": "role_e", "type": "import_role"},
            imp_role_links,
        )

        # include_tasks_to: role_a -> "subtasks.yml"
        inc_tasks_links = links_of("include_tasks_to")
        self.assertIn(
            {"source": "role_a", "target": "subtasks.yml", "type": "include_tasks"},
            inc_tasks_links,
        )

        # import_tasks_to: role_a -> "legacy.yml"
        imp_tasks_links = links_of("import_tasks_to")
        self.assertIn(
            {"source": "role_a", "target": "legacy.yml", "type": "import_tasks"},
            imp_tasks_links,
        )

    def test_output_graph_console_prints_header_and_yaml(self):
        graph_data = {"nodes": [{"id": "role_a"}], "links": []}
        buf = StringIO()
        with redirect_stdout(buf):
            output_graph(graph_data, "console", "role_a", "include_role_to")

        out = buf.getvalue()
        self.assertIn("--- role_a_include_role_to ---", out)
        self.assertIn("nodes:", out)
        self.assertIn("role_a", out)

    def test_output_graph_writes_json_file(self):
        graph_data = {"nodes": [{"id": "role_a"}], "links": []}
        # Use current working directory; file is small and cleaned manually.
        fname = "role_a_include_role_to.json"
        try:
            output_graph(graph_data, "json", "role_a", "include_role_to")
            self.assertTrue(os.path.exists(fname))

            with open(fname, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            self.assertEqual(graph_data, loaded)
        finally:
            if os.path.exists(fname):
                os.remove(fname)


if __name__ == "__main__":
    unittest.main()
