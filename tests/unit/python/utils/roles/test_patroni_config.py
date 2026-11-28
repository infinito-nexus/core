import unittest

from utils.cache.yaml import load_yaml_str
from utils.roles.patroni_config import (
    PatroniConfigError,
    dynamic_config,
    pg_hba,
    render_patroni_yml,
)

SUBNET = "192.168.200.0/24"
PARAMETERS = {"max_connections": 1000, "shared_buffers": "1536MB"}


def _render(**overrides):
    kwargs = {
        "scope": "postgres",
        "namespace": "/service/",
        "etcd_hosts": ["etcd-mgr-01:2379", "etcd-mgr-02:2379", "etcd-mgr-03:2379"],
        "etcd_cacert": "/etc/patroni/etcd-ca.crt",
        "etcd_username": "patroni",
        "etcd_password": "etcdpw",
        "restapi_port": 8008,
        "restapi_username": "patroni",
        "restapi_password": "restpw",
        "superuser": "postgres",
        "superuser_password": "superpw",
        "replication_user": "replicator",
        "replication_password": "replpw",
        "rewind_user": "rewinder",
        "rewind_password": "rewindpw",
        "data_dir": "/var/lib/postgresql/18/docker",
        "bin_dir": "/usr/lib/postgresql/18/bin",
        "postgres_port": 5432,
        "parameters": PARAMETERS,
        "replication_subnet": SUBNET,
    }
    kwargs.update(overrides)
    return load_yaml_str(render_patroni_yml(**kwargs))


class TestDynamicConfig(unittest.TestCase):
    def setUp(self):
        self.dcs = dynamic_config(PARAMETERS, SUBNET, "replicator", "rewinder")

    def test_durability_settings(self):
        self.assertEqual(self.dcs["synchronous_mode"], "quorum")
        self.assertEqual(self.dcs["synchronous_node_count"], 1)
        self.assertIs(self.dcs["synchronous_mode_strict"], True)
        self.assertIs(self.dcs["failsafe_mode"], True)

    def test_timings(self):
        self.assertEqual(
            (
                self.dcs["ttl"],
                self.dcs["loop_wait"],
                self.dcs["retry_timeout"],
                self.dcs["primary_start_timeout"],
            ),
            (20, 5, 7, 10),
        )
        self.assertLessEqual(
            self.dcs["loop_wait"] + 2 * self.dcs["retry_timeout"], self.dcs["ttl"]
        )

    def test_rewind_and_tuning(self):
        pg = self.dcs["postgresql"]
        self.assertIs(pg["use_pg_rewind"], True)
        self.assertEqual(pg["parameters"]["wal_log_hints"], "on")
        self.assertEqual(pg["parameters"]["max_connections"], 1000)
        self.assertEqual(pg["parameters"]["shared_buffers"], "1536MB")
        self.assertEqual(pg["pg_hba"], pg_hba(SUBNET, "replicator", "rewinder"))

    def test_tuning_cannot_disable_wal_log_hints(self):
        dcs = dynamic_config({"wal_log_hints": "off"}, SUBNET, "replicator", "rewinder")
        self.assertEqual(dcs["postgresql"]["parameters"]["wal_log_hints"], "on")


class TestPgHba(unittest.TestCase):
    def setUp(self):
        self.lines = pg_hba(SUBNET, "replicator", "rewinder")

    def test_local_peer_first(self):
        self.assertEqual(self.lines[0], "local all all peer")

    def test_replication_and_rewind_only_from_subnet(self):
        self.assertIn(f"host replication replicator {SUBNET} scram-sha-256", self.lines)
        self.assertIn(f"host all rewinder {SUBNET} scram-sha-256", self.lines)
        self.assertIn("host replication all all reject", self.lines)
        self.assertIn("host all rewinder all reject", self.lines)
        self.assertLess(
            self.lines.index("host all rewinder all reject"),
            self.lines.index("host all all all scram-sha-256"),
        )

    def test_patroni_reads_its_timeline_over_the_local_socket(self):
        local = "local replication replicator scram-sha-256"
        self.assertIn(local, self.lines)
        self.assertLess(
            self.lines.index(local),
            self.lines.index("host replication all all reject"),
        )
        self.assertNotIn(
            "host replication replicator 127.0.0.1/32", " ".join(self.lines)
        )

    def test_apps_scram_last(self):
        self.assertEqual(self.lines[-1], "host all all all scram-sha-256")
        self.assertFalse(any(" trust" in line or " md5" in line for line in self.lines))

    def test_rejects_bad_subnet(self):
        with self.assertRaises(PatroniConfigError):
            pg_hba("not-a-subnet", "replicator", "rewinder")


class TestRenderPatroniYml(unittest.TestCase):
    def setUp(self):
        self.cfg = _render()

    def test_member_identity_comes_from_env(self):
        self.assertEqual(self.cfg["scope"], "postgres")
        self.assertNotIn("name", self.cfg)
        self.assertNotIn("connect_address", self.cfg["restapi"])
        self.assertNotIn("connect_address", self.cfg["postgresql"])

    def test_local_superuser_connection_survives_a_password_rotation(self):
        self.assertIs(self.cfg["postgresql"]["use_unix_socket"], True)

    def test_local_replication_connection_uses_the_socket(self):
        self.assertIs(self.cfg["postgresql"]["use_unix_socket_repl"], True)

    def test_restapi_auth(self):
        self.assertEqual(self.cfg["restapi"]["listen"], "0.0.0.0:8008")
        self.assertEqual(
            self.cfg["restapi"]["authentication"],
            {"username": "patroni", "password": "restpw"},
        )
        self.assertEqual(
            self.cfg["ctl"]["authentication"],
            {"username": "patroni", "password": "restpw"},
        )

    def test_restapi_unsafe_calls_only_from_internal_overlay(self):
        self.assertEqual(self.cfg["restapi"]["allowlist"], [SUBNET])
        self.assertIs(self.cfg["restapi"]["allowlist_include_members"], True)

    def test_restapi_allowlist_normalises_subnet(self):
        cfg = _render(replication_subnet="10.9.8.7/24")
        self.assertEqual(cfg["restapi"]["allowlist"], ["10.9.8.0/24"])

    def test_restapi_rejects_bad_subnet(self):
        with self.assertRaises(PatroniConfigError):
            _render(replication_subnet="bogus")

    def test_etcd3(self):
        etcd = self.cfg["etcd3"]
        self.assertEqual(etcd["protocol"], "https")
        self.assertEqual(
            etcd["hosts"], ["etcd-mgr-01:2379", "etcd-mgr-02:2379", "etcd-mgr-03:2379"]
        )
        self.assertEqual(etcd["cacert"], "/etc/patroni/etcd-ca.crt")
        self.assertEqual((etcd["username"], etcd["password"]), ("patroni", "etcdpw"))
        self.assertEqual(self.cfg["namespace"], "/service/")

    def test_bootstrap_dcs_matches_dynamic_config(self):
        self.assertEqual(
            self.cfg["bootstrap"]["dcs"],
            dynamic_config(PARAMETERS, SUBNET, "replicator", "rewinder"),
        )

    def test_postgresql_section(self):
        pg = self.cfg["postgresql"]
        self.assertEqual(pg["listen"], "0.0.0.0:5432")
        self.assertEqual(pg["data_dir"], "/var/lib/postgresql/18/docker")
        self.assertEqual(pg["bin_dir"], "/usr/lib/postgresql/18/bin")
        auth = pg["authentication"]
        self.assertEqual(
            auth["superuser"], {"username": "postgres", "password": "superpw"}
        )
        self.assertEqual(
            auth["replication"], {"username": "replicator", "password": "replpw"}
        )
        self.assertEqual(
            auth["rewind"], {"username": "rewinder", "password": "rewindpw"}
        )

    def test_role_names_come_from_caller(self):
        cfg = _render(
            namespace="/other/",
            superuser="admin",
            replication_user="repl",
            rewind_user="rw",
        )
        self.assertEqual(cfg["namespace"], "/other/")
        auth = cfg["postgresql"]["authentication"]
        self.assertEqual(
            (
                auth["superuser"]["username"],
                auth["replication"]["username"],
                auth["rewind"]["username"],
            ),
            ("admin", "repl", "rw"),
        )
        self.assertIn(
            f"host replication repl {SUBNET} scram-sha-256",
            cfg["bootstrap"]["dcs"]["postgresql"]["pg_hba"],
        )

    def test_requires_etcd_hosts(self):
        with self.assertRaises(PatroniConfigError):
            _render(etcd_hosts=[])


if __name__ == "__main__":
    unittest.main()
