from __future__ import annotations

import itertools
import unittest

from utils.failover import procedures
from utils.failover.sampling import Round
from utils.failover.scenarios import get_scenario
from utils.failover.targets import RECLONE_CEILING_S

_GOOD = "start r 0\nack 1 200\nack 2 400\npresent 1\npresent 2\ndone\n"
_LOST = "start r 0\nack 1 200\nack 2 400\npresent 1\ndone\n"


class _FakeSampler:
    def __init__(self, rounds: list[Round]):
        self.rounds = rounds

    def stop(self) -> list[Round]:
        return self.rounds


class _FakeLab:
    """Records every adapter call; answers from ``answers``.

    Args:
        log: checker log every run returns.
        answers: method name -> return value overrides.
    """

    def __init__(self, log: str = _GOOD, **answers):
        self.log = log
        self.calls: list[str] = []
        self.spare = "w1"
        self.client_node = "w1"
        self.checker_nodes: list[str] = []
        self.managers = ["m1", "m2", "m3"]
        self.answers = {
            "primary_instance": "pg_pg-m2",
            "instances": ["pg_pg-m1", "pg_pg-m2", "pg_pg-m3"],
            "node_of": "m2",
            "live_managers": ["m1", "m2", "m3"],
            "wait_running": True,
            "wait_new_primary": "pg_pg-m1",
            "wait_node_status": True,
            "wait_full_strength": (True, "all streaming"),
            "redeploy": 0,
            "forget_and_replace": 0,
            "bump_engine_memory": 3,
            "form": "ha",
            "local_write": (False, "READONLY"),
            "ldap_unwilling": (True, "rc=53"),
            "run_probe": {},
            "endpoint_mode": "vip",
            "fire_backup": "/tmp/stamp",
            "verify_backup": (True, "restored"),
            "memberof_views": {"a": ["cn=g"], "b": ["cn=g"]},
            "elector_log": ["INFO ranked"],
        }
        self.answers.update(answers)

    def _call(self, name: str, *args):
        self.calls.append(":".join([name, *map(str, args)]))
        value = self.answers.get(name)
        return value(*args) if callable(value) else value

    def start_checker(self, run_id, duration_s):
        self.calls.append("start")
        self.checker_nodes.append(self.client_node)

    def finish_checker(self):
        self.calls.append("finish")

    def checker_log(self):
        return self.log

    def stop_checker(self, run_id):
        self.calls.append("stop")

    def writer_round(self):
        return Round(at_ms=0, writers={})

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *args, **kwargs: self._call(name, *args)


def _env(rounds: list[Round] | None = None, **kw) -> procedures.Env:
    clock = itertools.count(1000, 1000)
    return procedures.Env(
        duration_s=1,
        sleep=lambda _s: None,
        now_ms=lambda: next(clock),
        start_sampler=lambda _fn: _FakeSampler(rounds or []),
        **kw,
    )


def _run(lab, name: str, engine: str = "postgres", env=None):
    return procedures.run_procedure(lab, engine, get_scenario(name), env or _env())


def _without_plain(calls: list[str]) -> list[str]:
    return [c for c in calls if c not in ("start", "stop", "finish")]


class TestFaultProcedures(unittest.TestCase):
    def test_two_writers_heals_the_partition_before_finishing_the_checker(self):
        lab = _FakeLab()
        result = _run(lab, "two-writers", "mariadb")
        self.assertEqual(result.failures, [])
        self.assertEqual(
            lab.calls,
            [
                "primary_instance",
                "start",
                "inject_at:partition:pg_pg-m2",
                "heal:partition",
                "finish",
                "stop",
            ],
        )

    def test_two_writers_fails_on_a_long_double_writer_window(self):
        rounds = [
            Round(at_ms=0, writers={"a": True, "b": True}),
            Round(at_ms=30_000, writers={"a": False, "b": True}),
        ]
        result = _run(_FakeLab(), "two-writers", "mariadb", _env(rounds))
        self.assertTrue(any("renew deadline" in f for f in result.failures))

    def test_gtid_choice_lags_a_replica_then_kills_the_primary_and_restores_it(self):
        lab = _FakeLab()
        rounds = [
            Round(
                at_ms=3000,
                writers={"pg_pg-m1": False, "pg_pg-m3": False},
                gtids={"pg_pg-m1": "0-1-5", "pg_pg-m3": "0-1-9"},
            ),
            Round(
                at_ms=4000,
                writers={"pg_pg-m1": True, "pg_pg-m3": False},
                gtids={"pg_pg-m1": "0-1-5", "pg_pg-m3": "0-1-9"},
            ),
        ]
        result = _run(lab, "gtid-choice", "mariadb", _env(rounds))
        calls = _without_plain(lab.calls)
        self.assertEqual(
            calls,
            [
                "primary_instance",
                "instances",
                "stop_replica_sql:pg_pg-m1",
                "inject_at:kill:pg_pg-m2",
                "start_replica_sql:pg_pg-m1",
                "elector_log:pg_pg-m1",
            ],
        )
        self.assertTrue(any("pg_pg-m1 was promoted" in f for f in result.failures))
        self.assertIn("INFO ranked", result.notes)

    def test_ldap_writer_move_checks_the_demoted_writer_while_isolated(self):
        lab = _FakeLab()
        rounds = [Round(at_ms=5000, writers={"pg_pg-m1": True, "pg_pg-m2": False})]
        result = _run(lab, "ldap-writer-move", "openldap", _env(rounds))
        calls = _without_plain(lab.calls)
        self.assertEqual(calls[1], "inject_at:partition:pg_pg-m2")
        self.assertTrue(calls[2].startswith("ldap_unwilling:pg_pg-m2:"))
        self.assertEqual(calls[3], "heal:partition")
        self.assertEqual(result.failures, [])

    def test_ldap_writer_move_fails_when_the_demoted_writer_accepts(self):
        lab = _FakeLab(ldap_unwilling=(False, "rc=0"))
        rounds = [Round(at_ms=5000, writers={"pg_pg-m1": True})]
        result = _run(lab, "ldap-writer-move", "openldap", _env(rounds))
        self.assertTrue(any("did not refuse" in f for f in result.failures))

    def test_ldap_writer_move_fails_without_a_new_writer(self):
        result = _run(_FakeLab(), "ldap-writer-move", "openldap", _env([]))
        self.assertTrue(any("no new writer" in f for f in result.failures))

    def test_stale_master_is_restarted_after_promotion_then_watched(self):
        lab = _FakeLab()
        result = _run(lab, "redis-stale-master", "redis")
        calls = _without_plain(lab.calls)
        self.assertEqual(
            calls[:5],
            [
                "primary_instance",
                "inject_at:node:pg_pg-m2",
                "wait_new_primary:pg_pg-m2",
                "heal:node",
                "wait_running:pg_pg-m2:True",
            ],
        )
        self.assertEqual(
            len([c for c in calls if c.startswith("local_write")]),
            procedures.STALE_WATCH_S,
        )
        self.assertEqual(result.failures, [])

    def test_stale_master_taking_a_write_fails(self):
        lab = _FakeLab(local_write=(True, "OK"))
        result = _run(lab, "redis-stale-master", "redis")
        self.assertTrue(any("old master accepted" in f for f in result.failures))

    def test_partitioned_master_writing_past_the_lag_fails(self):
        lab = _FakeLab(local_write=(True, "OK"))
        result = _run(lab, "redis-partition", "redis")
        calls = _without_plain(lab.calls)
        self.assertEqual(calls[1], "inject_at:partition:pg_pg-m2")
        self.assertEqual(calls[-1], "heal:partition")
        self.assertTrue(any("old master accepted" in f for f in result.failures))

    def test_replicas_down_stall_scales_both_replicas_down_and_back(self):
        lab = _FakeLab()
        result = _run(lab, "replicas-down-stall")
        calls = _without_plain(lab.calls)
        self.assertEqual(
            calls,
            [
                "primary_instance",
                "instances",
                "scale:pg_pg-m1:0",
                "scale:pg_pg-m3:0",
                "wait_running:pg_pg-m1:False",
                "wait_running:pg_pg-m3:False",
                "scale:pg_pg-m1:1",
                "scale:pg_pg-m3:1",
                "wait_running:pg_pg-m1:True",
                "wait_running:pg_pg-m3:True",
            ],
        )
        self.assertTrue(any("did not resume" in f for f in result.failures))

    def test_replicas_down_stall_fails_on_an_ack_without_replicas(self):
        clock = itertools.count(100_000, 100_000)
        env = _env()
        env.now_ms = lambda: next(clock)
        log = "start r 0\nack 1 150000\nack 2 900000\npresent 1\npresent 2\ndone\n"
        result = _run(_FakeLab(log), "replicas-down-stall", env=env)
        self.assertEqual(len(result.failures), 1)
        self.assertIn("every replica down", result.failures[0])

    def test_replicas_come_back_even_when_one_never_stops(self):
        lab = _FakeLab(wait_running=False)
        with self.assertRaises(RuntimeError):
            _run(lab, "replicas-down-stall")
        self.assertIn("scale:pg_pg-m1:1", lab.calls)
        self.assertEqual(lab.calls[-1], "stop")


class TestDeployProcedures(unittest.TestCase):
    def test_rolling_bumps_redeploys_and_waits_while_the_checker_writes(self):
        lab = _FakeLab()
        result = _run(lab, "rolling")
        self.assertEqual(
            lab.calls,
            [
                "start",
                "bump_engine_memory:32",
                "redeploy",
                f"wait_full_strength:{RECLONE_CEILING_S}",
                "finish",
                "stop",
            ],
        )
        self.assertEqual(result.failures, [])

    def test_rolling_judges_loss_like_any_fault(self):
        result = _run(_FakeLab(_LOST), "rolling")
        self.assertTrue(any("lost" in f for f in result.failures))

    def test_a_failed_elector_roll_attaches_every_elector_log(self):
        result = _run(_FakeLab(_LOST), "rolling", "mariadb")
        self.assertIn("pg_pg-m3: INFO ranked", result.notes)

    def test_backup_restore_seeds_marks_fires_on_the_primary_host_and_restores(self):
        lab = _FakeLab(run_probe={"marker-write": "ok"})
        result = _run(lab, "backup-restore")
        self.assertEqual(
            [c.split(":")[0] for c in lab.calls],
            [
                "seed_backup",
                "run_probe",
                "primary_instance",
                "node_of",
                "fire_backup",
                "verify_backup",
            ],
        )
        self.assertEqual(result.failures, [])

    def test_a_backup_without_the_marker_says_whether_the_writer_kept_it(self):
        lab = _FakeLab(
            run_probe={"marker-write": "ok", "marker": "found"},
            verify_backup=(False, "replayed"),
        )
        result = _run(lab, "backup-restore")
        self.assertTrue(
            any(
                "the live writer reports the marker found" in f for f in result.failures
            )
        )

    def test_openldap_backup_needs_no_seed_row(self):
        lab = _FakeLab(run_probe={"marker-write": "ok"})
        _run(lab, "backup-restore", "openldap")
        self.assertNotIn("seed_backup", lab.calls)

    def test_failed_marker_write_stops_the_backup_case(self):
        lab = _FakeLab(run_probe={"marker-write": "fail"})
        result = _run(lab, "backup-restore")
        self.assertNotIn("fire_backup", [c.split(":")[0] for c in lab.calls])
        self.assertTrue(result.failures)

    def test_endpoint_idle_records_the_mode_and_waits_past_the_idle_time(self):
        lab = _FakeLab(run_probe={"idle": "ok"})
        result = _run(lab, "endpoint-idle", env=_env(idle_s=5))
        self.assertIn("endpoint mode vip", result.notes)
        self.assertIn("run_probe:idle:5", lab.calls)
        self.assertEqual(result.failures, [])

    def test_etcd_dr_writes_wipes_redeploys_then_reads_and_writes_again(self):
        lab = _FakeLab(
            run_probe=lambda mode, arg="": {"marker-write": "ok", "marker": "found"}
        )
        result = _run(lab, "etcd-dr")
        names = [c.split(":")[0] for c in lab.calls]
        self.assertEqual(
            names,
            [
                "run_probe",
                "wipe_etcd",
                "redeploy",
                "wait_full_strength",
                "run_probe",
                "start",
                "stop",
            ],
        )
        self.assertEqual(result.failures, [])

    def test_forget_reclone_loses_a_non_primary_manager_and_replaces_it(self):
        lab = _FakeLab()
        result = _run(lab, "forget-reclone")
        calls = _without_plain(lab.calls)
        self.assertEqual(
            calls,
            [
                "primary_instance",
                "node_of:pg_pg-m2",
                "live_managers",
                "crash_node:m3",
                "wait_node_status:m3:Down",
                "forget_and_replace:m3",
                calls[6],
            ],
        )
        self.assertTrue(calls[6].startswith("wait_full_strength:"))
        self.assertEqual(result.failures, [])

    def test_forget_reclone_writes_from_the_stack_host_not_the_promoted_spare(self):
        lab = _FakeLab()
        _run(lab, "forget-reclone")
        self.assertEqual(lab.checker_nodes[-1], "m1")
        self.assertEqual(lab.client_node, "w1")

    def test_forget_reclone_never_reaching_strength_fails(self):
        lab = _FakeLab(wait_full_strength=(False, "1 of 3 instances running"))
        result = _run(lab, "forget-reclone")
        self.assertTrue(any("re-clone" in f for f in result.failures))

    def test_openldap_reclone_compares_member_of(self):
        lab = _FakeLab(
            run_probe={"memberof-seed": "ok"},
            memberof_views={"a": ["cn=g"], "b": []},
        )
        result = _run(lab, "forget-reclone", "openldap")
        self.assertTrue(any("memberOf differs" in f for f in result.failures))

    def test_standalone_then_migration_carry_the_marker(self):
        env = _env()
        lab = _FakeLab(
            form="standalone", run_probe={"marker-write": "ok", "marker": "found"}
        )
        first = _run(lab, "standalone", env=env)
        self.assertEqual(first.failures, [])
        self.assertIn("set_engine_hosts:['m1']", lab.calls)
        self.assertIn("marker", env.state)
        lab.answers["form"] = "ha"
        lab.calls.clear()
        second = _run(lab, "migration", env=env)
        self.assertEqual(second.failures, [])
        self.assertEqual(
            lab.calls[:3],
            ["live_managers", "set_engine_hosts:['m1', 'm2', 'm3']", "redeploy"],
        )

    def test_migration_without_a_standalone_marker_fails(self):
        result = _run(_FakeLab(), "migration")
        self.assertTrue(result.failures)

    def test_consumer_ddl_runs_the_probe(self):
        lab = _FakeLab(run_probe={"ddl": "fail"})
        result = _run(lab, "consumer-ddl")
        self.assertEqual(lab.calls, ["run_probe:ddl:"])
        self.assertTrue(result.failures)


if __name__ == "__main__":
    unittest.main()
