import shutil
import tempfile
import unittest
from pathlib import Path

from utils.cache.yaml import dump_yaml
from utils.roles.mapping import (
    ROLE_FILE_META_MAIN,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)
from utils.roles.order import (
    build_dependency_graph,
    find_cycle,
    ordered_roles,
    topological_sort,
)


class TestRoleOrder(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.roles = {
            "grp-a": {"run_after": [], "application_id": "a"},
            "grp-b": {"run_after": ["grp-a"], "application_id": "b"},
            "grp-c": {"run_after": ["grp-b"], "application_id": "c"},
            "grp-d": {"run_after": [], "application_id": "d"},
        }

        for role_name, meta in self.roles.items():
            role_path = Path(self.temp_dir) / role_name
            (role_path / "meta").mkdir(parents=True, exist_ok=True)
            (role_path / "vars").mkdir(parents=True, exist_ok=True)

            dump_yaml(
                str(role_path / ROLE_FILE_META_SERVICES),
                {role_name: {"run_after": meta["run_after"]}},
            )
            dump_yaml(str(role_path / ROLE_FILE_META_MAIN), {})
            dump_yaml(
                str(role_path / ROLE_FILE_VARS_MAIN),
                {"application_id": meta["application_id"]},
            )

    def tearDown(self):
        ordered_roles.cache_clear()
        shutil.rmtree(self.temp_dir)

    def test_dependency_graph_and_sort(self):
        graph, in_degree, _roles = build_dependency_graph(self.temp_dir)

        self.assertEqual(graph["grp-a"], ["grp-b"])
        self.assertEqual(graph["grp-b"], ["grp-c"])
        self.assertEqual(in_degree["grp-a"], 0)
        self.assertEqual(in_degree["grp-d"], 0)

        order = topological_sort(graph, in_degree)
        self.assertTrue(
            order.index("grp-a") < order.index("grp-b") < order.index("grp-c")
        )

    def test_no_cycle_in_a_linear_chain(self):
        _graph, _in_degree, roles = build_dependency_graph(self.temp_dir)
        self.assertIsNone(find_cycle(roles))

    def test_ordered_roles_pairs_role_with_application_id(self):
        entries = ordered_roles(self.temp_dir, "grp")

        self.assertEqual(sorted(e["app"] for e in entries), ["a", "b", "c", "d"])
        for entry in entries:
            self.assertEqual(entry["role"], f"grp-{entry['app']}")

        apps = [e["app"] for e in entries]
        self.assertTrue(
            apps.index("a") < apps.index("b") < apps.index("c"),
            "the group must be returned in run_after order",
        )

    def test_missing_application_id_is_rejected(self):
        dump_yaml(str(Path(self.temp_dir) / "grp-d" / ROLE_FILE_VARS_MAIN), {})
        with self.assertRaises(ValueError):
            ordered_roles(self.temp_dir, "grp")


if __name__ == "__main__":
    unittest.main()
