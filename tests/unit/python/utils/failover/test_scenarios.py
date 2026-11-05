from __future__ import annotations

import unittest

from utils.failover.procedures import PROCEDURES
from utils.failover.scenarios import (
    ENGINES,
    SCENARIOS,
    get_scenario,
    scenarios_for,
)
from utils.failover.swarm import commands as swarm
from utils.failover.targets import ENGINES as BUDGET_ENGINES
from utils.failover.targets import budget_s

_APPLICABILITY = {
    "steady-state": ENGINES,
    "consumer-ddl": ("postgres", "mariadb"),
    "instance-kill": ENGINES,
    "node-crash": ENGINES,
    "node-hang": ENGINES,
    "node-partition": ENGINES,
    "two-writers": ("mariadb", "openldap"),
    "gtid-choice": ("mariadb",),
    "ldap-writer-move": ("openldap",),
    "redis-stale-master": ("redis",),
    "redis-partition": ("redis",),
    "replicas-down-stall": ("postgres", "mariadb"),
    "leader-loss": ENGINES,
    "rolling": ENGINES,
    "backup-restore": ("postgres", "mariadb", "openldap"),
    "endpoint-idle": ENGINES,
    "etcd-dr": ("postgres", "mariadb", "openldap"),
    "forget-reclone": ENGINES,
    "standalone": ENGINES,
    "migration": ENGINES,
}


class TestScenarioRegistry(unittest.TestCase):
    def test_names_are_unique(self):
        names = [s.name for s in SCENARIOS]
        self.assertEqual(len(names), len(set(names)))

    def test_applicability_matrix(self):
        self.assertEqual({s.name for s in SCENARIOS}, set(_APPLICABILITY))
        for scenario in SCENARIOS:
            for engine in ENGINES:
                with self.subTest((scenario.name, engine)):
                    self.assertEqual(
                        scenario.applies_to(engine),
                        engine in _APPLICABILITY[scenario.name],
                    )

    def test_scenarios_for_keeps_run_order(self):
        names = [s.name for s in scenarios_for("redis")]
        self.assertEqual(names, [s.name for s in SCENARIOS if s.applies_to("redis")])
        with self.assertRaises(KeyError):
            scenarios_for("mongodb")

    def test_parts_split_every_case_exactly_once(self):
        for engine in ENGINES:
            with self.subTest(engine):
                in_place = scenarios_for(engine, "in-place")
                rebuild = scenarios_for(engine, "rebuild")
                self.assertEqual(in_place + rebuild, scenarios_for(engine))
        self.assertEqual(
            [s.name for s in scenarios_for("postgres", "rebuild")],
            ["etcd-dr", "forget-reclone", "standalone", "migration"],
        )
        with self.assertRaises(KeyError):
            scenarios_for("postgres", "everything")

    def test_rebuilding_cases_run_last_and_standalone_precedes_migration(self):
        names = [s.name for s in SCENARIOS]
        self.assertEqual(names[-2:], ["standalone", "migration"])
        self.assertLess(names.index("etcd-dr"), names.index("forget-reclone"))

    def test_every_case_is_either_plain_or_scripted(self):
        for scenario in SCENARIOS:
            with self.subTest(scenario.name):
                self.assertFalse(scenario.injection and scenario.procedure)
                if scenario.procedure:
                    self.assertIn(scenario.procedure, PROCEDURES)

    def test_every_injection_has_an_adapter_command_and_a_heal(self):
        for scenario in SCENARIOS:
            if scenario.injection is None:
                continue
            with self.subTest(scenario.name):
                argv = swarm.inject_argv(
                    scenario.injection, node="n1", network="lab", container="c1"
                )
                self.assertEqual(argv[0], "docker")
                swarm.heal_argv(scenario.injection, node="n1", network="lab", ip="ip")

    def test_every_scenario_has_a_budget_for_every_engine(self):
        self.assertEqual(set(ENGINES), set(BUDGET_ENGINES))
        for scenario in SCENARIOS:
            for engine in BUDGET_ENGINES:
                with self.subTest((scenario.name, engine)):
                    self.assertGreater(budget_s(engine, scenario.fault), 0)

    def test_suite_injects_real_faults(self):
        self.assertTrue(any(s.injection for s in SCENARIOS))

    def test_lookup_by_name(self):
        self.assertEqual(get_scenario("node-crash").fault, "node")
        with self.assertRaises(KeyError):
            get_scenario("nope")


if __name__ == "__main__":
    unittest.main()
