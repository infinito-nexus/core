from __future__ import annotations

import tempfile
import unittest

from infinito_elector_src.mariadb import GtidPosition, MariaDBRole
from infinito_elector_src.roles import (
    ReseedRequired,
    RestartRequired,
    RoleError,
    choose,
)

from . import _NAME  # noqa: F401  side-effect import registers infinito_elector_src


class FakeServers:
    """Answers the mariadb client per target (``local`` or a peer host)."""

    def __init__(self, answers: dict[str, dict[str, str]]) -> None:
        self.answers = answers
        self.calls: list[tuple[str, str]] = []

    def __call__(self, argv, stdin) -> str:
        target = argv[argv.index("-h") + 1] if "-h" in argv else "local"
        self.calls.append((target, stdin))
        server = self.answers.get(target)
        if server is None:
            raise RoleError(f"{target} unreachable")
        for prefix, answer in server.items():
            if stdin.startswith(prefix):
                return answer
        return ""


def _role(answers, replication_password="s'cret") -> tuple[MariaDBRole, FakeServers]:  # noqa: S107 - test fixture value
    run = FakeServers(answers)
    role = MariaDBRole(
        host_id="m1",
        peers=["m1", "m2", "m3"],
        defaults_file="/run/secrets/elector.cnf",
        socket="/run/mysqld/mysqld.sock",
        peer_address=lambda host: f"mariadb-{host}",
        local_user="mysql",
        replication_user="repl",
        replication_password=replication_password,
        run=run,
        recovered_marker=tempfile.NamedTemporaryFile(delete=False).name,  # noqa: SIM115 - the role removes it
    )
    return role, run


class TestGtidPosition(unittest.TestCase):
    def test_orders_by_sequence(self) -> None:
        self.assertLess(GtidPosition.parse("0-1-99"), GtidPosition.parse("0-2-100"))

    def test_multi_domain_sums(self) -> None:
        self.assertEqual(GtidPosition.parse("0-1-10,1-1-5").total, 15)

    def test_empty_is_zero(self) -> None:
        self.assertEqual(GtidPosition.parse("").total, 0)

    def test_garbage_raises(self) -> None:
        with self.assertRaises(RoleError):
            GtidPosition.parse("nope")


class TestGtidChoice(unittest.TestCase):
    def test_most_advanced_reachable_peer_wins(self) -> None:
        role, _ = _role(
            {
                "local": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-100"},
                "mariadb-m2": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-120"},
            }
        )
        ranks = {"m1": role.rank(), **role.peer_ranks()}
        self.assertEqual(set(ranks), {"m1", "m2"})
        self.assertEqual(choose(ranks), "m2")

    def test_a_received_but_unapplied_write_counts(self) -> None:
        role, _ = _role(
            {
                "local": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-934"},
                "mariadb-m2": {
                    "SELECT @@GLOBAL.gtid_current_pos": "0-1-934",
                    "SHOW SLAVE STATUS": "Gtid_IO_Pos: 0-1-935",
                },
            }
        )
        self.assertEqual(choose({"m1": role.rank(), **role.peer_ranks()}), "m2")

    def test_the_bootstrap_marker_lets_the_first_writer_promote_alone(self) -> None:
        with tempfile.NamedTemporaryFile() as marker:
            role, _ = _role({"local": {}})
            role._bootstrap_marker = marker.name
            self.assertEqual(role.quorum(), 1)

    def test_a_newly_silent_peer_blocks_promotion_until_the_grace_ends_in_five(
        self,
    ) -> None:
        now = [100.0]
        role, _ = _role(
            {
                "local": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-473"},
                "mariadb-m2": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-473"},
                "mariadb-m3": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-473"},
            }
        )
        role.peers = ["m2", "m3", "m4", "m5"]
        role._bootstrap_marker = "/nonexistent/.infinito-ha-bootstrap"
        role._clock = lambda: now[0]
        role.peer_ranks()
        self.assertEqual(role.quorum(), 5)
        now[0] += 8.0
        role.peer_ranks()
        self.assertEqual(role.quorum(), 3)

    def test_three_instances_promote_on_a_majority_without_waiting(self) -> None:
        role, _ = _role(
            {
                "local": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-473"},
                "mariadb-m2": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-473"},
            }
        )
        role._bootstrap_marker = "/nonexistent/.infinito-ha-bootstrap"
        role._clock = lambda: 100.0
        role.peer_ranks()
        self.assertEqual(role.quorum(), 2)

    def test_a_peer_that_answers_again_is_no_longer_silent(self) -> None:
        now = [100.0]
        answers = {"local": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-473"}}
        role, _ = _role(answers)
        role._bootstrap_marker = "/nonexistent/.infinito-ha-bootstrap"
        role._clock = lambda: now[0]
        role.peer_ranks()
        answers["mariadb-m2"] = {"SELECT @@GLOBAL.gtid_current_pos": "0-1-474"}
        answers["mariadb-m3"] = {"SELECT @@GLOBAL.gtid_current_pos": "0-1-474"}
        role.peer_ranks()
        self.assertEqual(role.quorum(), 2)

    def test_without_the_marker_a_majority_is_needed(self) -> None:
        role, _ = _role({"local": {}})
        role._bootstrap_marker = "/nonexistent/.infinito-ha-bootstrap"
        self.assertEqual(role.quorum(), 2)

    def test_ties_go_to_the_lowest_host_id(self) -> None:
        position = GtidPosition.parse("0-1-7")
        self.assertEqual(choose({"m3": position, "m1": position, "m2": position}), "m1")

    def test_self_wins_when_ahead(self) -> None:
        role, _ = _role(
            {
                "local": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-130"},
                "mariadb-m2": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-120"},
                "mariadb-m3": {"SELECT @@GLOBAL.gtid_current_pos": "0-1-130"},
            }
        )
        self.assertEqual(choose({"m1": role.rank(), **role.peer_ranks()}), "m1")


class TestTransitions(unittest.TestCase):
    def test_promotion_waits_for_the_relay_log_then_opens_writes(self) -> None:
        role, run = _role(
            {
                "local": {
                    "SHOW SLAVE STATUS": "Gtid_IO_Pos: 0-1-50\nSlave_SQL_Running: Yes",
                    "SELECT MASTER_GTID_WAIT": "0",
                }
            }
        )
        role.become_writer()
        statements = [stdin for _, stdin in run.calls]
        wait = next(
            i
            for i, s in enumerate(statements)
            if s.startswith("SELECT MASTER_GTID_WAIT")
        )
        self.assertIn("'0-1-50'", statements[wait])
        self.assertLess(statements.index("STOP SLAVE IO_THREAD"), wait)
        self.assertLess(statements.index("START SLAVE SQL_THREAD"), wait)
        self.assertLess(wait, statements.index("STOP SLAVE"))
        self.assertEqual(statements[-1], "SET GLOBAL read_only = 0")

    def test_promotion_aborts_when_the_relay_log_lags(self) -> None:
        role, run = _role(
            {
                "local": {
                    "SHOW SLAVE STATUS": "Gtid_IO_Pos: 0-1-50",
                    "SELECT MASTER_GTID_WAIT": "-1",
                }
            }
        )
        with self.assertRaises(RoleError):
            role.become_writer()
        self.assertNotIn("SET GLOBAL read_only = 0", [s for _, s in run.calls])

    def test_follow_reads_a_rotated_replication_password(self) -> None:
        passwords = iter(["old", "new"])
        role, run = _role(
            {"local": {"SHOW SLAVE STATUS": "Master_Host: mariadb-m1"}},
            replication_password=lambda: next(passwords),
        )
        role.follow("m2")
        role.follow("m3")
        changes = [s for _, s in run.calls if s.startswith("CHANGE MASTER")]
        self.assertIn("MASTER_PASSWORD='old'", changes[0])
        self.assertIn("MASTER_PASSWORD='new'", changes[1])

    SEMI_SYNC_ON = "SET GLOBAL rpl_semi_sync_master_enabled = 1"
    SEMI_SYNC_OFF = "SET GLOBAL rpl_semi_sync_master_enabled = 0"

    def test_only_the_writer_waits_for_semi_sync_acks(self) -> None:
        role, run = _role({"local": {}})
        role.follow("m2")
        statements = [s for _, s in run.calls]
        self.assertLess(
            statements.index(self.SEMI_SYNC_OFF), statements.index("START SLAVE")
        )
        self.assertNotIn(self.SEMI_SYNC_ON, statements)
        role.become_writer()
        statements = [s for _, s in run.calls]
        self.assertLess(
            statements.index(self.SEMI_SYNC_ON),
            statements.index("SET GLOBAL read_only = 0"),
        )

    def test_follow_uses_gtid_slave_pos_and_feeds_the_password_on_stdin(self) -> None:
        role, run = _role({"local": {}})
        role.follow("m2")
        change = next(s for _, s in run.calls if s.startswith("CHANGE MASTER"))
        self.assertIn("MASTER_HOST='mariadb-m2'", change)
        self.assertIn("MASTER_USE_GTID=slave_pos", change)
        self.assertIn("MASTER_CONNECT_RETRY=1", change)
        self.assertIn("'s\\'cret'", change)
        role.follow("m2")
        self.assertEqual(sum(s.startswith("CHANGE MASTER") for _, s in run.calls), 1)

    RESET_SLAVE_POS = "SET GLOBAL gtid_slave_pos = @@GLOBAL.gtid_current_pos"

    def test_a_former_writer_starts_from_its_own_position(self) -> None:
        role, run = _role({"local": {}})
        role.follow("m2")
        statements = [s for _, s in run.calls]
        reset = statements.index(self.RESET_SLAVE_POS)
        change = next(i for i, s in enumerate(statements) if s.startswith("CHANGE"))
        self.assertLess(reset, change)

    def test_a_former_writer_restarts_once_before_it_follows(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            role, run = _role({"local": {}})
            role._recovered_marker = f"{scratch}/.infinito-ha-recovered"
            with self.assertRaises(RestartRequired):
                role.follow("m2")
            self.assertFalse(any(s.startswith("CHANGE") for _, s in run.calls))
            role.follow("m2")
            self.assertTrue(any(s.startswith("CHANGE") for _, s in run.calls))

    def test_a_running_replica_keeps_its_slave_position(self) -> None:
        role, run = _role({"local": {"SHOW SLAVE STATUS": "Master_Host: mariadb-m3"}})
        role.follow("m2")
        self.assertNotIn(self.RESET_SLAVE_POS, [s for _, s in run.calls])

    def test_local_calls_use_socket_auth(self) -> None:
        seen: list[list[str]] = []

        def run(argv, stdin):
            seen.append(list(argv))
            return "0"

        role = MariaDBRole(
            host_id="m1",
            peers=["m1", "m2"],
            defaults_file="/run/secrets/elector.cnf",
            socket="/run/mysqld/mysqld.sock",
            peer_address=lambda host: f"mariadb-{host}",
            replication_user="repl",
            replication_password="pw",
            local_user="mysql",
            run=run,
        )
        role.is_writable()
        role.peer_ranks()
        local, remote = seen
        self.assertEqual(local[1:4], ["--no-defaults", "--user", "mysql"])
        self.assertFalse(any(a.startswith("--defaults-extra-file") for a in local))
        self.assertIn("--defaults-extra-file=/run/secrets/elector.cnf", remote)

    def test_read_only_toggle(self) -> None:
        role, run = _role({"local": {"SELECT @@GLOBAL.read_only": "1"}})
        self.assertFalse(role.is_writable())
        role.become_read_only()
        self.assertEqual(run.calls[-1][1], "SET GLOBAL read_only = 1")

    def test_writable_reads_both_the_numeric_and_the_enum_form(self) -> None:
        for answer, writable in (
            ("0", True),
            ("OFF", True),
            ("1", False),
            ("ON", False),
            ("NO_LOCK", False),
            ("NO_LOCK_NO_ADMIN", False),
        ):
            with self.subTest(read_only=answer):
                role, _ = _role({"local": {"SELECT @@GLOBAL.read_only": answer}})
                self.assertEqual(role.is_writable(), writable)


class TestLostRelayLog(unittest.TestCase):
    def _candidate(self) -> MariaDBRole:
        role, _ = _role(
            {
                "local": {
                    "SELECT @@GLOBAL.gtid_current_pos": "0-1-1552",
                    "SHOW SLAVE STATUS": "Gtid_IO_Pos: 0-1-1632",
                    "SELECT MASTER_GTID_WAIT": "0",
                }
            }
        )
        return role

    def test_a_candidate_behind_its_claim_is_not_promoted(self) -> None:
        role = self._candidate()
        self.assertEqual(role.rank().total, 1632)
        with self.assertRaises(RoleError):
            role.become_writer()
        self.assertEqual(role.rank().total, 1552)

    def test_following_a_writer_restores_the_received_rank(self) -> None:
        role = self._candidate()
        role.rank()
        with self.assertRaises(RoleError):
            role.become_writer()
        role.attach_seed("m2", "0-1-1552")
        self.assertEqual(role.rank().total, 1632)


class TestDivergence(unittest.TestCase):
    DIVERGED = "Slave_IO_Running: No\nLast_IO_Errno: 1236\nLast_IO_Error: not in the master's binlog"

    def _following(self, status: str) -> tuple[MariaDBRole, list[float]]:
        role, _ = _role({"local": {"SHOW SLAVE STATUS": status}})
        now = [0.0]
        role._clock = lambda: now[0]
        role._following = "m2"
        return role, now

    def test_a_lasting_1236_asks_for_a_reseed(self) -> None:
        role, now = self._following(self.DIVERGED)
        role.watch()
        now[0] = 59.0
        role.watch()
        now[0] = 60.0
        with self.assertRaises(ReseedRequired):
            role.watch()

    def test_a_cleared_error_restarts_the_grace(self) -> None:
        role, now = self._following(self.DIVERGED)
        role.watch()
        role._run.answers["local"]["SHOW SLAVE STATUS"] = "Slave_IO_Running: Yes"
        now[0] = 30.0
        role.watch()
        role._run.answers["local"]["SHOW SLAVE STATUS"] = self.DIVERGED
        now[0] = 61.0
        role.watch()
        self.assertIsNotNone(role._diverged_since)

    def test_an_instance_that_follows_nobody_never_asks(self) -> None:
        role, now = self._following(self.DIVERGED)
        role._following = None
        now[0] = 1000.0
        role.watch()

    def test_only_a_healthy_instance_donates(self) -> None:
        for status, writable, kind in (
            ("", "0", "writer"),
            ("Slave_IO_Running: Yes\nSlave_SQL_Running: Yes", "1", "replica"),
            (self.DIVERGED + "\nSlave_SQL_Running: Yes", "1", None),
        ):
            with self.subTest(kind=kind):
                role, _ = _role(
                    {
                        "local": {
                            "SHOW SLAVE STATUS": status,
                            "SELECT @@GLOBAL.read_only": writable,
                        }
                    }
                )
                self.assertEqual(role.donor_kind(), kind)

    def test_attach_starts_from_the_seed_position(self) -> None:
        role, run = _role({"local": {}})
        role.attach_seed("m3", "0-7-42")
        statements = [s for _, s in run.calls]
        self.assertIn("SET GLOBAL gtid_slave_pos = '0-7-42'", statements)
        change = next(s for s in statements if s.startswith("CHANGE MASTER"))
        self.assertIn("MASTER_HOST='mariadb-m3'", change)
        self.assertEqual(role._following, "m3")


if __name__ == "__main__":
    unittest.main()
