import importlib.util
import unittest
from pathlib import Path

from utils import PROJECT_ROOT

_spec = importlib.util.spec_from_file_location(
    "mariadb_ha",
    str(Path(PROJECT_ROOT) / "roles/svc-db-mariadb/filter_plugins/mariadb_ha.py"),
)
mariadb_ha = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mariadb_ha)


class TestServerId(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(
            mariadb_ha.mariadb_server_id("mgr-01"),
            mariadb_ha.mariadb_server_id("mgr-01"),
        )

    def test_in_range(self):
        for host_id in ("a", "mgr-01", "mgr-02", "x" * 200):
            value = mariadb_ha.mariadb_server_id(host_id)
            self.assertGreaterEqual(value, 1)
            self.assertLessEqual(value, 4294967295)

    def test_distinct_hosts_differ(self):
        self.assertNotEqual(
            mariadb_ha.mariadb_server_id("mgr-01"),
            mariadb_ha.mariadb_server_id("mgr-02"),
        )

    def test_empty_host_id_rejected(self):
        with self.assertRaises(ValueError):
            mariadb_ha.mariadb_server_id("")


class TestServerIds(unittest.TestCase):
    def test_maps_every_instance(self):
        instances = [{"host_id": "mgr-01"}, {"host_id": "mgr-02"}]
        result = mariadb_ha.mariadb_server_ids(instances)
        self.assertEqual(set(result), {"mgr-01", "mgr-02"})
        self.assertEqual(result["mgr-01"], mariadb_ha.mariadb_server_id("mgr-01"))

    def test_collision_rejected(self):
        original = mariadb_ha.mariadb_server_id
        mariadb_ha.mariadb_server_id = lambda host_id: 7
        try:
            with self.assertRaises(ValueError):
                mariadb_ha.mariadb_server_ids([{"host_id": "a"}, {"host_id": "b"}])
        finally:
            mariadb_ha.mariadb_server_id = original

    def test_filters_registered(self):
        filters = mariadb_ha.FilterModule().filters()
        self.assertIn("mariadb_server_ids", filters)
        self.assertIn("mariadb_sql_literal", filters)
        self.assertIn("mariadb_sql_body", filters)
        self.assertIn("mariadb_identifier", filters)


class TestSqlEscaping(unittest.TestCase):
    def test_literal_doubles_quotes_and_escapes_backslashes(self):
        self.assertEqual(mariadb_ha.mariadb_sql_literal("a'b\\c"), "'a''b\\\\c'")

    def test_literal_of_a_trailing_backslash_cannot_eat_the_quote(self):
        self.assertEqual(mariadb_ha.mariadb_sql_literal("x\\"), "'x\\\\'")

    def test_body_escapes_without_wrapping(self):
        self.assertEqual(mariadb_ha.mariadb_sql_body("o'k\\"), "o''k\\\\")

    def test_identifier_doubles_backticks(self):
        self.assertEqual(mariadb_ha.mariadb_identifier("a`b"), "a``b")


class TestHostMasks(unittest.TestCase):
    def test_cidr_becomes_netmask_notation(self):
        self.assertEqual(
            mariadb_ha.mariadb_host_masks(["192.168.231.32/27", "192.168.230.0/24"]),
            ["192.168.231.32/255.255.255.224", "192.168.230.0/255.255.255.0"],
        )

    def test_host_bits_are_cleared_and_duplicates_dropped(self):
        self.assertEqual(
            mariadb_ha.mariadb_host_masks(["10.0.0.5/16", "10.0.0.0/16"]),
            ["10.0.0.0/255.255.0.0"],
        )


if __name__ == "__main__":
    unittest.main()
