"""Scripted failover cases: each arranges the lab, faults it, and judges the result."""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any

from utils.failover.checker import acks_between, audit, max_write_gap_s
from utils.failover.junit import CaseResult
from utils.failover.procedure_kit import (
    DEMOTE_MARGIN_S,
    LAG_BUILD_S,
    PARTITION_WATCH_S,
    RECOVER_S,
    ROLLING_DELTA_MB,
    SETTLE_S,
    STALE_WATCH_S,
    STALL_GRACE_S,
    STALL_HOLD_S,
    Env,
    absorb,
    judge,
    need_ok,
    probe_ok,
    steady,
    watch_local_writes,
    with_checker,
)
from utils.failover.runner import FAULT_HOLD_S, unfinished
from utils.failover.sampling import (
    dual_writer_detail,
    dual_writer_windows,
    first_new_writer,
    gtid_choice_violation,
)
from utils.failover.scenarios import ELECTOR_ENGINES
from utils.failover.targets import (
    MIN_REPLICAS_MAX_LAG_S,
    RECLONE_CEILING_S,
    RENEW_DEADLINE_S,
    evaluate_isolated_master,
    evaluate_reclone,
    evaluate_stall,
    evaluate_writer_move,
    evaluate_writer_overlap,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from utils.failover.scenarios import Scenario


def consumer_ddl(lab, engine: str, env: Env, result: CaseResult) -> None:
    probe_ok(lab, result, "ddl", key="ddl", want="ok")


def two_writers(lab, engine: str, env: Env, result: CaseResult) -> None:
    writer = lab.primary_instance()
    sampler = env.start_sampler(lab.writer_round)

    def action() -> None:
        lab.inject_at("partition", writer)
        try:
            env.sleep(FAULT_HOLD_S)
        finally:
            lab.heal("partition")
        env.sleep(SETTLE_S)

    try:
        run = with_checker(lab, engine, result.name, env, action)
    finally:
        rounds = sampler.stop()
    judge(result, engine, "node", run)
    overlap = evaluate_writer_overlap(dual_writer_windows(rounds))
    absorb(result, overlap)
    if overlap.failures:
        result.notes.append(dual_writer_detail(rounds))
    result.notes.append(f"{len(rounds)} writer sampling rounds")


def gtid_choice(lab, engine: str, env: Env, result: CaseResult) -> None:
    primary = lab.primary_instance()
    lagging = next(s for s in lab.instances() if s != primary)
    lab.stop_replica_sql(lagging)
    sampler = env.start_sampler(lab.writer_round)
    fault: dict[str, int] = {}

    def action() -> None:
        env.sleep(LAG_BUILD_S)
        fault["at"] = env.now_ms()
        lab.inject_at("kill", primary)
        env.sleep(FAULT_HOLD_S)

    try:
        run = with_checker(lab, engine, result.name, env, action)
    finally:
        rounds = sampler.stop()
        lab.start_replica_sql(lagging)
    judge(result, engine, "kill", run)
    if "at" in fault:
        violation = gtid_choice_violation(rounds, fault_ms=fault["at"], old=primary)
        promoted = first_new_writer(rounds, after_ms=fault["at"], old=primary)
        if violation:
            result.failures.append(violation)
            if promoted:
                result.notes.extend(lab.elector_log(promoted[0]))
        result.notes.append(
            f"stopped the SQL thread of {lagging}; promoted {promoted[0] if promoted else 'none'}"
        )


def ldap_writer_move(lab, engine: str, env: Env, result: CaseResult) -> None:
    writer = lab.primary_instance()
    sampler = env.start_sampler(lab.writer_round)
    fault: dict[str, Any] = {}

    def action() -> None:
        fault["at"] = env.now_ms()
        lab.inject_at("partition", writer)
        try:
            env.sleep(RENEW_DEADLINE_S + DEMOTE_MARGIN_S)
            fault["unwilling"] = lab.ldap_unwilling(writer, secrets.token_hex(4))
            env.sleep(max(0.0, FAULT_HOLD_S - RENEW_DEADLINE_S - DEMOTE_MARGIN_S))
        finally:
            lab.heal("partition")

    try:
        run = with_checker(lab, engine, result.name, env, action)
    finally:
        rounds = sampler.stop()
    judge(result, engine, "node", run)
    if "at" not in fault:
        return
    moved = first_new_writer(rounds, after_ms=fault["at"], old=writer)
    moved_after_s = (moved[1] - fault["at"]) / 1000.0 if moved else None
    absorb(result, evaluate_writer_move(engine, "node", moved_after_s=moved_after_s))
    absorb(result, evaluate_writer_overlap(dual_writer_windows(rounds)))
    unwilling, detail = fault.get("unwilling", (False, "not attempted"))
    if not unwilling:
        result.failures.append(
            f"demoted writer {writer} did not refuse a write: {detail}"
        )


def redis_stale_master(lab, engine: str, env: Env, result: CaseResult) -> None:
    master = lab.primary_instance()
    watch: dict[str, Any] = {}

    def action() -> None:
        lab.inject_at("node", master)
        try:
            watch["new"] = lab.wait_new_primary(master)
        finally:
            lab.heal("node")
        watch["restarted"] = env.now_ms()
        lab.wait_running(master, True)
        watch["accepted"] = watch_local_writes(lab, env, master, STALE_WATCH_S, "stale")

    run = with_checker(lab, engine, result.name, env, action)
    judge(result, engine, "node", run)
    if not watch.get("new"):
        result.failures.append(
            "Sentinel promoted no new master while the old one was down"
        )
    if "restarted" in watch:
        absorb(
            result,
            evaluate_isolated_master(
                accepted_ms=watch.get("accepted", []),
                isolated_ms=watch["restarted"],
                limit_s=None,
            ),
        )


def redis_partition(lab, engine: str, env: Env, result: CaseResult) -> None:
    master = lab.primary_instance()
    watch: dict[str, Any] = {}

    def action() -> None:
        watch["at"] = env.now_ms()
        lab.inject_at("partition", master)
        try:
            watch["accepted"] = watch_local_writes(
                lab, env, master, PARTITION_WATCH_S, "partition"
            )
        finally:
            lab.heal("partition")

    run = with_checker(lab, engine, result.name, env, action)
    judge(result, engine, "node", run)
    if "at" in watch:
        absorb(
            result,
            evaluate_isolated_master(
                accepted_ms=watch.get("accepted", []),
                isolated_ms=watch["at"],
                limit_s=MIN_REPLICAS_MAX_LAG_S,
            ),
        )


def replicas_down_stall(lab, engine: str, env: Env, result: CaseResult) -> None:
    primary = lab.primary_instance()
    replicas = [s for s in lab.instances() if s != primary]
    window: dict[str, int] = {}

    def action() -> None:
        try:
            for replica in replicas:
                lab.scale(replica, 0)
            for replica in replicas:
                if not lab.wait_running(replica, False):
                    raise RuntimeError(f"{replica} kept running after scale 0")
            window["down"] = env.now_ms()
            env.sleep(STALL_HOLD_S)
            window["up"] = env.now_ms()
        finally:
            for replica in replicas:
                lab.scale(replica, 1)
        for replica in replicas:
            lab.wait_running(replica, True)
        env.sleep(RECOVER_S)

    run = with_checker(lab, engine, result.name, env, action)
    if not run.done:
        result.failures.append(unfinished(run))
        return
    lost = audit(run)
    if lost:
        result.failures.append(
            f"{len(lost)} acknowledged writes lost (first seq {lost[0]})"
        )
    if "up" in window:
        acked = acks_between(run, window["down"] + STALL_GRACE_S * 1000, window["up"])
        resumed = any(at > window["up"] for at in run.acks.values())
        absorb(result, evaluate_stall(acked_while_down=acked, resumed=resumed))
    result.notes.append(
        f"longest write gap {max_write_gap_s(run):.1f}s (stall expected)"
    )


def rolling(lab, engine: str, env: Env, result: CaseResult) -> None:
    def action() -> None:
        if not lab.bump_engine_memory(ROLLING_DELTA_MB):
            raise RuntimeError("no host_vars carry the engine's mem_limit to change")
        if need_ok(result, lab.redeploy(), "rolling redeploy"):
            ok, detail = lab.wait_full_strength(RECLONE_CEILING_S)
            if not ok:
                result.failures.append(
                    f"not back at full strength after the roll: {detail}"
                )

    run = with_checker(lab, engine, result.name, env, action)
    judge(result, engine, "rolling", run)
    if result.failures and engine in ELECTOR_ENGINES:
        for service in lab.instances():
            result.notes.extend(
                f"{service}: {line}" for line in lab.elector_log(service)
            )


def backup_restore(lab, engine: str, env: Env, result: CaseResult) -> None:
    token = secrets.token_hex(8)
    if engine != "openldap":
        lab.seed_backup()
    if not probe_ok(lab, result, "marker-write", token, key="marker-write", want="ok"):
        return
    node = lab.node_of(lab.primary_instance())
    stamp = lab.fire_backup(node)
    ok, detail = lab.verify_backup(node, stamp, token)
    result.notes.append(detail)
    if not ok:
        live = lab.run_probe("marker-read", token).get("marker")
        result.failures.append(
            f"backup on {node} does not restore the marker: {detail}; "
            f"the live writer reports the marker {live}"
        )


def endpoint_idle(lab, engine: str, env: Env, result: CaseResult) -> None:
    result.notes.append(f"endpoint mode {lab.endpoint_mode()}")
    probe_ok(
        lab,
        result,
        "idle",
        str(env.idle_s),
        key="idle",
        want="ok",
        timeout_s=env.idle_s + 300,
    )


def etcd_dr(lab, engine: str, env: Env, result: CaseResult) -> None:
    token = secrets.token_hex(8)
    if not probe_ok(lab, result, "marker-write", token, key="marker-write", want="ok"):
        return
    lab.wipe_etcd()
    if not need_ok(result, lab.redeploy(), "redeploy onto an empty etcd"):
        return
    ok, detail = lab.wait_full_strength(RECLONE_CEILING_S)
    if not ok:
        result.failures.append(
            f"engine did not recover after the etcd rebuild: {detail}"
        )
    probe_ok(lab, result, "marker-read", token, key="marker", want="found")
    steady(lab, engine, env, result, "after etcd rebuild")


def forget_reclone(lab, engine: str, env: Env, result: CaseResult) -> None:
    primary_node = lab.node_of(lab.primary_instance())
    victims = [m for m in lab.live_managers()[1:] if m not in (primary_node, lab.spare)]
    if not victims:
        result.failures.append("no manager besides STACK_HOST and the primary to lose")
        return
    victim = victims[0]
    if engine == "openldap":
        probe_ok(lab, result, "memberof-seed", key="memberof-seed", want="ok")
    timing: dict[str, Any] = {}

    def action() -> None:
        lab.crash_node(victim)
        if not lab.wait_node_status(victim, "Down"):
            raise RuntimeError(f"Swarm never reported {victim} Down")
        timing["start"] = time.monotonic()
        if need_ok(result, lab.forget_and_replace(victim), "swarm-forget-node"):
            left = RECLONE_CEILING_S - (time.monotonic() - timing["start"])
            ok, detail = lab.wait_full_strength(max(0.0, left))
            timing["elapsed"] = time.monotonic() - timing["start"] if ok else None
            result.notes.append(detail)

    spare = lab.client_node
    lab.client_node = lab.managers[0]
    try:
        run = with_checker(lab, engine, result.name, env, action)
    finally:
        lab.client_node = spare
    judge(result, engine, "node", run)
    absorb(result, evaluate_reclone(timing.get("elapsed")))
    if engine == "openldap":
        views = lab.memberof_views()
        if len({tuple(v) for v in views.values()}) != 1 or not any(views.values()):
            result.failures.append(f"memberOf differs across instances: {views}")


def standalone(lab, engine: str, env: Env, result: CaseResult) -> None:
    hosts = lab.live_managers()
    lab.wipe_engine()
    lab.set_engine_hosts(hosts[:1])
    if not need_ok(result, lab.redeploy(), "standalone deploy"):
        return
    if lab.form() != "standalone":
        result.failures.append("one listed host did not render the standalone form")
        return
    token = secrets.token_hex(8)
    if probe_ok(lab, result, "marker-write", token, key="marker-write", want="ok"):
        env.state["marker"] = token
    steady(lab, engine, env, result, "standalone")


def migration(lab, engine: str, env: Env, result: CaseResult) -> None:
    token = env.state.get("marker")
    if not token:
        result.failures.append("the standalone case left no seeded marker to migrate")
        return
    lab.set_engine_hosts(lab.live_managers())
    if not need_ok(result, lab.redeploy(), "migration deploy"):
        return
    if lab.form() != "ha":
        result.failures.append("growing the group did not render the HA form")
        return
    ok, detail = lab.wait_full_strength(RECLONE_CEILING_S)
    if not ok:
        result.failures.append(f"migrated engine not at full strength: {detail}")
    probe_ok(lab, result, "marker-read", token, key="marker", want="found")
    steady(lab, engine, env, result, "after migration")


PROCEDURES: dict[str, Callable[[Any, str, Env, CaseResult], None]] = {
    "consumer_ddl": consumer_ddl,
    "two_writers": two_writers,
    "gtid_choice": gtid_choice,
    "ldap_writer_move": ldap_writer_move,
    "redis_stale_master": redis_stale_master,
    "redis_partition": redis_partition,
    "replicas_down_stall": replicas_down_stall,
    "rolling": rolling,
    "backup_restore": backup_restore,
    "endpoint_idle": endpoint_idle,
    "etcd_dr": etcd_dr,
    "forget_reclone": forget_reclone,
    "standalone": standalone,
    "migration": migration,
}


def run_procedure(lab, engine: str, scenario: Scenario, env: Env) -> CaseResult:
    """Run one scripted case and return its JUnit result.

    Args:
        lab: mode adapter.
        engine: engine under test.
        scenario: registry entry with a ``procedure``.
        env: clocks and shared state.
    """
    started = time.monotonic()
    result = CaseResult(name=scenario.name)
    PROCEDURES[scenario.procedure](lab, engine, env, result)
    result.seconds = time.monotonic() - started
    return result
