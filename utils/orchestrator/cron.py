"""The orchestrator's cron runner, the stack-free part.

Given a role's cron.yml entries and the current UTC time, decide which fire.
A quality gate outranks the crons: while the machine's gate lock is held, no
``start`` fires (the lane stays paused), at night as well. An entry's optional
``condition`` (a load rule such as ``host-load-below-30``) must hold; the
orchestrator measures the load and passes which conditions hold, so this
module stays deterministic and testable.
"""

from __future__ import annotations

from datetime import UTC, datetime


def _field_matches(spec: str, value: int) -> bool:
    for part in spec.split(","):
        step = 1
        body = part
        if "/" in part:
            body, step_text = part.split("/", 1)
            step = int(step_text)
        if body == "*":
            lo, hi = None, None
        elif "-" in body:
            lo_text, hi_text = body.split("-", 1)
            lo, hi = int(lo_text), int(hi_text)
        else:
            lo = hi = int(body)
        if lo is None:
            if value % step == 0:
                return True
            continue
        if lo <= value <= hi and (value - lo) % step == 0:
            return True
    return False


def cron_matches(expr: str, when: datetime) -> bool:
    """Return whether the 5-field UTC cron ``expr`` matches ``when``.

    Fields are minute hour day-of-month month day-of-week, with ``*``,
    ``*/n``, ``a-b`` and comma lists. Day-of-week is 0 to 6 with 0 Sunday.
    """
    minute, hour, dom, month, dow = expr.split()
    return (
        _field_matches(minute, when.minute)
        and _field_matches(hour, when.hour)
        and _field_matches(dom, when.day)
        and _field_matches(month, when.month)
        and _field_matches(dow, when.isoweekday() % 7)
    )


def due(
    entries: list[dict],
    when: datetime,
    *,
    gate_locked: bool = False,
    conditions_met: frozenset[str] = frozenset(),
    held: frozenset[str] = frozenset(),
    blocked: frozenset[str] = frozenset(),
) -> list[dict]:
    """Return the cron entries that fire at ``when``.

    An entry fires when its schedule matches and its condition (if any) holds.
    While the gate lock is held, a ``start`` entry does not fire; a ``pause``
    entry still does, so the gate can quiesce a lane. A ``start`` whose routine
    the owner has put on hold, or that carries a recorded owner-only blocker,
    does not fire either: a cron re-delivery is never read as fresh consent, so
    the routine stays quiet across every later firing until the owner lifts the
    hold or clears the blocker.

    Args:
        entries: the role's cron.yml list.
        when: the current UTC time.
        gate_locked: whether the machine's gate lock is held.
        conditions_met: the condition names the orchestrator measured as true.
        held: the routines the owner has put on hold.
        blocked: the routines with a recorded owner-only blocker.
    """
    out = []
    for entry in entries:
        if not cron_matches(entry["schedule"], when):
            continue
        condition = entry.get("condition")
        if condition is not None and condition not in conditions_met:
            continue
        if entry.get("action") == "start" and (
            gate_locked
            or entry.get("routine") in held
            or entry.get("routine") in blocked
        ):
            continue
        out.append(entry)
    return out


def gate_discarded(*, long_job_ran: bool, tree_changed: bool) -> bool:
    """Return whether a quality gate run is discarded rather than judged.

    A gate during which a long job ran beside it, or the tree under test
    changed, is not a red or green result; it is thrown away.

    Args:
        long_job_ran: whether a long-running job ran on the machine during the
            gate.
        tree_changed: whether the tree under test changed during the gate.
    """
    return long_job_ran or tree_changed


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    night = {
        "name": "night",
        "schedule": "0 23 * * *",
        "routine": "translate",
        "action": "start",
    }
    day = {
        "name": "day",
        "schedule": "*/10 7-22 * * *",
        "routine": "translate",
        "condition": "host-load-below-30",
        "action": "start",
    }
    sweep = {
        "name": "s",
        "schedule": "0 4 * * *",
        "routine": "maintainer",
        "action": "start",
    }
    entries = [night, day, sweep]

    at_2300 = datetime(2026, 10, 24, 23, 0, tzinfo=UTC)
    _expect(
        [e["name"] for e in due(entries, at_2300)] == ["night"], "night cron missed"
    )
    at_0410 = datetime(2026, 10, 24, 4, 10, tzinfo=UTC)
    _expect(due(entries, at_0410) == [], "0410 matched something")
    at_0400 = datetime(2026, 10, 24, 4, 0, tzinfo=UTC)
    _expect([e["name"] for e in due(entries, at_0400)] == ["s"], "daily sweep missed")
    at_1210 = datetime(2026, 10, 24, 12, 10, tzinfo=UTC)
    _expect(due(entries, at_1210) == [], "day rule fired without its condition")
    met = frozenset({"host-load-below-30"})
    _expect(
        [e["name"] for e in due(entries, at_1210, conditions_met=met)] == ["day"],
        "day rule missed under load",
    )
    _expect(
        due(entries, at_2300, gate_locked=True) == [],
        "start fired while gate locked",
    )
    _expect(
        not cron_matches("*/10 7-22 * * *", datetime(2026, 10, 24, 6, 0, tzinfo=UTC)),
        "fired before the window",
    )

    sunday = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)
    _expect(sunday.isoweekday() == 7, "fixture date is not a Sunday")
    _expect(cron_matches("0 9 * * 0", sunday), "day-of-week 0 (Sunday) missed")
    _expect(not cron_matches("0 9 * * 1", sunday), "Monday schedule matched on Sunday")

    pause = {
        "name": "p",
        "schedule": "0 7 * * *",
        "routine": "translate",
        "action": "pause",
    }
    at_0700 = datetime(2026, 10, 24, 7, 0, tzinfo=UTC)
    _expect(
        [e["name"] for e in due([pause], at_0700, gate_locked=True)] == ["p"],
        "gate wrongly suppressed a pause",
    )

    held = frozenset({"maintainer"})
    _expect(due([sweep], at_0400, held=held) == [], "held routine fired on cron")
    _expect(due([sweep], at_0400, blocked=held) == [], "blocked routine fired on cron")
    _expect(
        [e["name"] for e in due([sweep], at_0400)] == ["s"], "sweep missed off hold"
    )
    _expect(
        gate_discarded(long_job_ran=True, tree_changed=False),
        "gate beside a long job not discarded",
    )
    _expect(
        not gate_discarded(long_job_ran=False, tree_changed=False),
        "clean gate wrongly discarded",
    )
    print("orchestrator cron self-check ok")


if __name__ == "__main__":
    _demo()
