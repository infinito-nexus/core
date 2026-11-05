"""Scenario registry of the failover suite."""

from __future__ import annotations

from dataclasses import dataclass

ENGINES = ("postgres", "mariadb", "redis", "openldap")
SQL_ENGINES = ("postgres", "mariadb")
ELECTOR_ENGINES = ("mariadb", "openldap")
ETCD_ENGINES = ("postgres", "mariadb", "openldap")
PARTS = ("in-place", "rebuild")


@dataclass(frozen=True)
class Scenario:
    """One failover suite case.

    Args:
        name: stable case name, used in JUnit output.
        fault: budget column (``kill``, ``node``, ``rolling`` or ``none``).
        injection: adapter fault (``kill``, ``node``, ``hang``, ``partition``,
            ``leader``) for the plain inject-hold-heal flow, or ``None``.
        procedure: name of the scripted procedure in
            ``utils.failover.procedures`` that runs this case instead of the
            plain flow, or ``None``.
        engines: engines the case applies to.
        rebuild: the case rebuilds the engine or its coordination store, so
            it runs in the ``rebuild`` part on a lab of its own.
    """

    name: str
    fault: str
    injection: str | None = None
    procedure: str | None = None
    engines: tuple[str, ...] = ENGINES
    rebuild: bool = False

    def applies_to(self, engine: str) -> bool:
        return engine in self.engines


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("steady-state", "none"),
    Scenario("consumer-ddl", "none", procedure="consumer_ddl", engines=SQL_ENGINES),
    Scenario("instance-kill", "kill", "kill"),
    Scenario("node-crash", "node", "node"),
    Scenario("node-hang", "node", "hang"),
    Scenario("node-partition", "node", "partition"),
    Scenario("two-writers", "node", procedure="two_writers", engines=ELECTOR_ENGINES),
    Scenario("gtid-choice", "kill", procedure="gtid_choice", engines=("mariadb",)),
    Scenario(
        "ldap-writer-move", "node", procedure="ldap_writer_move", engines=("openldap",)
    ),
    Scenario(
        "redis-stale-master", "node", procedure="redis_stale_master", engines=("redis",)
    ),
    Scenario(
        "redis-partition", "node", procedure="redis_partition", engines=("redis",)
    ),
    Scenario(
        "replicas-down-stall",
        "none",
        procedure="replicas_down_stall",
        engines=SQL_ENGINES,
    ),
    Scenario("leader-loss", "node", "leader"),
    Scenario("rolling", "rolling", procedure="rolling"),
    Scenario(
        "backup-restore",
        "none",
        procedure="backup_restore",
        engines=("postgres", "mariadb", "openldap"),
    ),
    Scenario("endpoint-idle", "none", procedure="endpoint_idle"),
    Scenario(
        "etcd-dr", "none", procedure="etcd_dr", engines=ETCD_ENGINES, rebuild=True
    ),
    Scenario("forget-reclone", "node", procedure="forget_reclone", rebuild=True),
    Scenario("standalone", "none", procedure="standalone", rebuild=True),
    Scenario("migration", "none", procedure="migration", rebuild=True),
)


def get_scenario(name: str) -> Scenario:
    for scenario in SCENARIOS:
        if scenario.name == name:
            return scenario
    raise KeyError(name)


def scenarios_for(engine: str, part: str | None = None) -> tuple[Scenario, ...]:
    """Return the scenarios that apply to one engine, in run order.

    Args:
        engine: one of ``ENGINES``.
        part: one of ``PARTS`` to keep only that part's cases, or ``None``
            for every case.
    """
    if engine not in ENGINES:
        raise KeyError(engine)
    if part is not None and part not in PARTS:
        raise KeyError(part)
    return tuple(
        s
        for s in SCENARIOS
        if s.applies_to(engine) and (part is None or s.rebuild == (part == "rebuild"))
    )
