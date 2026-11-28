from __future__ import annotations

import json
import unittest

from utils.failover import engines


class TestNames(unittest.TestCase):
    def test_stack_and_member_names(self):
        self.assertEqual(engines.stack_of("postgres"), "postgres")
        self.assertEqual(engines.role_of("redis"), "svc-db-redis")
        self.assertEqual(
            engines.member_of("postgres", "postgres_postgres-mgr-02"), "postgres-mgr-02"
        )

    def test_patroni_config_comes_from_the_role_vars(self):
        self.assertTrue(engines.patroni_config().endswith("patroni.yml"))
        user, argv = engines.patroni_list()
        self.assertEqual(user, "postgres")
        self.assertIn(engines.patroni_config(), argv)


class TestCommandsCarryNoCredential(unittest.TestCase):
    def test_sql_uses_peer_auth_or_the_elector_defaults_file(self):
        user, argv = engines.sql("postgres", "SELECT 1")
        self.assertEqual((user, argv[0], argv[-1]), ("postgres", "psql", "SELECT 1"))
        user, argv = engines.sql("mariadb", "SELECT 1")
        self.assertIsNone(user)
        self.assertIn("$ELECTOR_MARIADB_DEFAULTS_FILE", argv[2])
        self.assertEqual(argv[3], "SELECT 1")
        with self.assertRaises(ValueError):
            engines.sql("redis", "SET")

    def test_redis_cli_reads_the_password_from_the_container_env(self):
        argv = engines.redis_cli("SET", "k", "1")
        self.assertIn('REDISCLI_AUTH="$REDIS_PASSWORD"', argv[2])
        self.assertEqual(argv[-3:], ["SET", "k", "1"])

    def test_switchover_names_leader_and_candidate(self):
        user, argv = engines.patroni_switchover("postgres", "postgres-a", "postgres-b")
        self.assertEqual(user, "postgres")
        self.assertEqual(
            argv[-6:],
            [
                "postgres",
                "--leader",
                "postgres-a",
                "--candidate",
                "postgres-b",
                "--force",
            ],
        )

    def test_ldap_add_entry_builds_a_device(self):
        argv, stdin = engines.ldap_add_entry("cn=x-1,ou=failover-check,dc=a")
        self.assertEqual(argv[0], "ldapadd")
        self.assertIn("ldapi:///", argv)
        self.assertIn("cn: x-1\n", stdin)


class TestParsers(unittest.TestCase):
    def test_ldap_values_are_case_insensitive(self):
        text = "dn: dc=a\ncontextCSN: 1#000\ncontextcsn: 2#000\nother: x\n"
        self.assertEqual(engines.ldap_values(text, "contextCSN"), ["1#000", "2#000"])

    def test_unwilling_to_perform(self):
        self.assertTrue(engines.ldap_unwilling(53, ""))
        self.assertTrue(
            engines.ldap_unwilling(1, "ldap_add: Server is unwilling to perform (53)")
        )
        self.assertFalse(engines.ldap_unwilling(0, "adding new entry"))

    def test_slave_status(self):
        text = "*** 1. row ***\n Slave_IO_Running: Yes\n Slave_SQL_Running: No\n"
        status = engines.parse_slave_status(text)
        self.assertFalse(engines.replica_running(status))
        status["Slave_SQL_Running"] = "Yes"
        self.assertTrue(engines.replica_running(status))

    def test_errant_gtid_is_fatal(self):
        status = engines.parse_slave_status(
            " Slave_IO_Running: No\n Last_IO_Errno: 1236\n"
        )
        self.assertTrue(engines.replica_fatal(status))

    def test_connecting_replica_is_not_fatal(self):
        status = engines.parse_slave_status(
            " Slave_IO_Running: Connecting\n Last_IO_Errno: 2003\n"
        )
        self.assertFalse(engines.replica_fatal(status))

    def test_patroni_strength(self):
        rows = [
            {"Member": "a", "Role": "Leader", "State": "running"},
            {"Member": "b", "Role": "Quorum Standby", "State": "streaming"},
            {"Member": "c", "Role": "Replica", "State": "streaming"},
        ]
        self.assertTrue(engines.patroni_strength(json.dumps(rows), 3)[0])
        rows[2]["State"] = "starting"
        ok, detail = engines.patroni_strength(json.dumps(rows), 3)
        self.assertFalse(ok)
        self.assertIn("c=Replica/starting", detail)
        self.assertFalse(engines.patroni_strength("not json", 3)[0])

    def test_redis_info(self):
        info = "# Replication\r\nrole:master\r\nconnected_slaves:2\r\n"
        self.assertEqual(engines.redis_connected_slaves(info.replace("\r", "")), 2)
        self.assertEqual(engines.redis_role(info.replace("\r", "")), "master")
        self.assertTrue(engines.redis_write_accepted("OK\n"))
        self.assertFalse(engines.redis_write_accepted("READONLY You can't write"))

    def test_dump_database(self):
        self.assertEqual(
            engines.dump_database("/b/x/sql/failover.backup.sql"), "failover"
        )
        self.assertEqual(engines.dump_database("/b/x/sql/postgres.sql"), "postgres")


class TestCsnsConverged(unittest.TestCase):
    def test_writes_landing_mid_check_still_converge(self) -> None:
        csns = {
            "a": ("20261017222635.306364Z#000000#059#000000",),
            "b": ("20261017222635.773318Z#000000#059#000000",),
            "c": ("20261017222636.236431Z#000000#059#000000",),
        }
        self.assertTrue(engines.csns_converged(csns, 5.0))

    def test_a_stalled_instance_diverges(self) -> None:
        csns = {
            "a": ("20261017121740.820893Z#000000#059#000000",),
            "b": ("20261017121343.875141Z#000000#059#000000",),
        }
        self.assertFalse(engines.csns_converged(csns, 5.0))

    def test_a_missing_server_id_diverges(self) -> None:
        csns = {
            "a": (
                "20261017121740.820893Z#000000#059#000000",
                "20261017121551.384876Z#000000#b17#000000",
            ),
            "b": ("20261017121740.820893Z#000000#059#000000",),
        }
        self.assertFalse(engines.csns_converged(csns, 5.0))

    def test_no_csn_is_not_converged(self) -> None:
        self.assertFalse(engines.csns_converged({"a": (), "b": ()}, 5.0))


class TestScratch(unittest.TestCase):
    def test_scratch_runs_without_network_or_password(self):
        argv = engines.scratch_run("postgres", name="s", image="img")
        self.assertIn("none", argv)
        self.assertIn("POSTGRES_HOST_AUTH_METHOD=trust", argv)
        self.assertEqual(argv[-2:], ["img", "postgres"])
        self.assertEqual(
            engines.scratch_run("mariadb", name="s", image="img")[-1], "mariadbd"
        )
        with self.assertRaises(ValueError):
            engines.scratch_run("redis", name="s", image="img")

    def test_scratch_clients(self):
        self.assertIn("failover", engines.scratch_load("mariadb", "failover"))
        self.assertEqual(
            engines.scratch_sql("postgres", "postgres", "SELECT 1")[-1], "SELECT 1"
        )
        self.assertEqual(engines.scratch_ready("mariadb")[0], "mariadb-admin")

    def test_postgres_scratch_is_ready_only_once_it_listens_on_tcp(self):
        self.assertEqual(
            engines.scratch_ready("postgres"),
            ["pg_isready", "-h", "127.0.0.1", "-U", "postgres"],
        )

    def test_mariadb_scratch_is_ready_only_once_it_listens_on_tcp(self):
        ready = engines.scratch_ready("mariadb")
        self.assertIn("--protocol=tcp", ready)
        self.assertIn("127.0.0.1", ready)


if __name__ == "__main__":
    unittest.main()
