import unittest

from utils.roles.db.instances import DbInstancesError
from utils.roles.db.primary import (
    client_command,
    ha_primary_address,
    is_ha,
    primary_address,
)

NODES = ["m1", "m2", "m3"]
BIN = "/usr/bin/resolve-db-primary"


def _groups(app_id, hosts):
    return {app_id: hosts, "svc-swarm-node": NODES}


class TestIsHa(unittest.TestCase):
    def test_three_hosts_in_swarm(self):
        self.assertTrue(
            is_ha("svc-db-postgres", _groups("svc-db-postgres", NODES), "swarm")
        )

    def test_one_host_is_standalone(self):
        self.assertFalse(
            is_ha("svc-db-postgres", _groups("svc-db-postgres", NODES[:1]), "swarm")
        )

    def test_compose_is_standalone(self):
        self.assertFalse(
            is_ha("svc-db-postgres", _groups("svc-db-postgres", NODES), "compose")
        )

    def test_coordination_store_has_no_primary(self):
        self.assertFalse(is_ha("svc-dcs-etcd", _groups("svc-dcs-etcd", NODES), "swarm"))

    def test_engine_without_ha_meta(self):
        self.assertFalse(
            is_ha("svc-db-qdrant", _groups("svc-db-qdrant", NODES), "swarm")
        )

    def test_no_groups(self):
        self.assertFalse(is_ha("svc-db-postgres", None, "swarm"))


class TestPrimaryAddress(unittest.TestCase):
    def test_quotes_every_part(self):
        self.assertEqual(
            primary_address(BIN, "postgres", "postgres"),
            '"$(/usr/bin/resolve-db-primary postgres postgres)"',
        )


class TestHaPrimaryAddress(unittest.TestCase):
    def _address(self, hosts, bin_resolver=BIN, mode="swarm"):
        return ha_primary_address(
            "svc-db-redis",
            _groups("svc-db-redis", hosts),
            mode,
            bin_resolver=bin_resolver,
            stack="redis",
            engine="redis",
        )

    def test_ha_form_resolves_the_primary(self):
        self.assertEqual(
            self._address(NODES), '"$(/usr/bin/resolve-db-primary redis redis)"'
        )

    def test_standalone_form_returns_none(self):
        self.assertIsNone(self._address(NODES[:1]))
        self.assertIsNone(self._address(NODES, mode="compose"))

    def test_standalone_needs_no_resolver(self):
        self.assertIsNone(self._address(NODES[:1], bin_resolver=""))

    def test_ha_form_requires_the_resolver(self):
        with self.assertRaises(DbInstancesError):
            self._address(NODES, bin_resolver="")


class TestClientCommand(unittest.TestCase):
    def _client(self, dbtype, ha):
        return client_command(
            dbtype,
            address='"$(/usr/bin/resolve-container-id postgres postgres)"',
            ha=ha,
            bin_client="/usr/bin/db-client",
            stack=dbtype,
            network=dbtype,
            host=dbtype,
            port=5432 if dbtype == "postgres" else 3306,
        )

    def test_standalone_postgres_execs_into_the_container_over_tcp(self):
        self.assertEqual(
            self._client("postgres", ha=False),
            'container exec -i -e PGPASSWORD "$(/usr/bin/resolve-container-id postgres postgres)" psql -h 127.0.0.1',
        )

    def test_standalone_mariadb_keeps_the_socket(self):
        self.assertTrue(self._client("mariadb", ha=False).endswith(" mariadb"))

    def test_ha_postgres_runs_through_the_write_endpoint(self):
        self.assertEqual(
            self._client("postgres", ha=True),
            "/usr/bin/db-client postgres postgres postgres psql -h postgres -p 5432",
        )

    def test_ha_mariadb_uses_its_port_flag(self):
        self.assertEqual(
            self._client("mariadb", ha=True),
            "/usr/bin/db-client mariadb mariadb mariadb mariadb -h mariadb -P 3306",
        )

    def test_an_engine_without_a_client_returns_nothing(self):
        self.assertEqual(self._client("redis", ha=False), "")


if __name__ == "__main__":
    unittest.main()
