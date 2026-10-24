"""Does the agents bundle fit its resource budget.

The bundle fits when ``agents.max_running`` times the largest runtime memory
reservation, plus the infrastructure the bundle always runs, stays within the
repository's per-variant budget. Only ``max_running`` agents run at once, so
the cap is bounded by the largest single runtime, not the sum of all declared
runtimes. This is the deterministic fit check; the reservations and the cap
come from the inventory and meta/services.yml.
"""

from __future__ import annotations


def agents_reservation(max_running: int, runtime_reservations: dict[str, int]) -> int:
    """Return the memory the running agents may reserve at once: ``max_running``
    times the largest single runtime reservation (0 when none run).

    Args:
        max_running: the cap on concurrently running agents.
        runtime_reservations: runtime name to its memory reservation in bytes.
    """
    if max_running <= 0 or not runtime_reservations:
        return 0
    return max_running * max(runtime_reservations.values())


def fits(
    max_running: int,
    runtime_reservations: dict[str, int],
    infrastructure: int,
    cap: int,
) -> bool:
    """Return whether the bundle fits: agents reservation plus infrastructure
    within the per-variant ``cap`` (all in bytes)."""
    return agents_reservation(max_running, runtime_reservations) + infrastructure <= cap


def _expect(condition: bool, message: object) -> None:
    if not condition:
        raise AssertionError(message)


def _demo() -> None:
    gib = 1024**3
    runtimes = {"hermes": 4 * gib, "openclaw": 6 * gib, "claude-code": 2 * gib}
    _expect(
        agents_reservation(3, runtimes) == 18 * gib,
        "did not use the largest reservation",
    )
    _expect(agents_reservation(0, runtimes) == 0, "zero max_running reserves nothing")
    _expect(agents_reservation(2, {}) == 0, "no runtimes reserves nothing")
    _expect(fits(3, runtimes, 10 * gib, 32 * gib), "28 GiB should fit 32")
    _expect(not fits(3, runtimes, 20 * gib, 32 * gib), "38 GiB must not fit 32")
    _expect(fits(2, runtimes, 18 * gib, 32 * gib), "12+18 = 30 should fit")
    print("budget fit self-check ok")


if __name__ == "__main__":
    _demo()
