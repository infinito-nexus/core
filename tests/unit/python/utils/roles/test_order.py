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
    stable_order_after,
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


class TestStableOrderAfter(unittest.TestCase):
    NAMES = ("keycloak", "matomo", "docs", "stalwart", "jitsi")

    def test_no_constraint_keeps_the_order(self):
        self.assertEqual(stable_order_after(list(self.NAMES), {}), list(self.NAMES))

    def test_a_name_after_all_others_moves_last_and_nothing_else_moves(self):
        others = [name for name in self.NAMES if name != "docs"]
        result = stable_order_after(list(self.NAMES), {"docs": others})
        self.assertEqual(result, [*others, "docs"])

    def test_a_satisfied_constraint_moves_nothing(self):
        result = stable_order_after(list(self.NAMES), {"stalwart": ["matomo"]})
        self.assertEqual(result, list(self.NAMES))

    def test_names_outside_the_list_constrain_nothing(self):
        result = stable_order_after(
            list(self.NAMES), {"matomo": ["absent"], "docs": ["jitsi", "gone"]}
        )
        self.assertEqual(result, ["keycloak", "matomo", "stalwart", "jitsi", "docs"])

    def test_a_name_listing_itself_raises(self):
        with self.assertRaises(RuntimeError):
            stable_order_after(list(self.NAMES), {"docs": ["docs"]})

    def test_a_cycle_raises_and_names_its_members(self):
        with self.assertRaises(RuntimeError) as ctx:
            stable_order_after(list(self.NAMES), {"docs": ["jitsi"], "jitsi": ["docs"]})
        self.assertIn("docs", str(ctx.exception))
        self.assertIn("jitsi", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
