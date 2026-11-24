import argparse
import unittest

from infinito_elector_src.__main__ import build_donor


def _args(**overrides):
    values = {
        "engine": "mariadb",
        "seed_port": 4444,
        "seed_relay": "relay:4445",
        "replication_password_file": "/run/secrets/repl",
        "mariadb_local_user": "mysql",
        "mariadb_socket": "/run/mysqld/mysqld.sock",
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class TestBuildDonor(unittest.TestCase):
    def test_openldap_has_no_seed_handler(self):
        self.assertIsNone(build_donor(_args(engine="openldap"), role=object()))

    def test_mariadb_without_a_seed_port_has_no_seed_handler(self):
        self.assertIsNone(build_donor(_args(seed_port=None), role=object()))

    def test_mariadb_with_a_seed_port_serves_seed_requests(self):
        handler = build_donor(_args(), role=object())
        self.assertTrue(callable(handler))
        self.assertEqual(handler.__name__, "handle")


if __name__ == "__main__":
    unittest.main()
