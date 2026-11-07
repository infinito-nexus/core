from __future__ import annotations

from typing import TYPE_CHECKING

from utils.runner.jobs import JobError, parse_duration

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from utils.runner.jobs import Job

OK = 0
WARN = 1
CRIT = 2
UNKNOWN = 3
WARN_KEY = "INFINITO_HELD_JOB_WARN_AGE"
CRIT_KEY = "INFINITO_HELD_JOB_CRIT_AGE"


def thresholds(env: Mapping[str, str]) -> tuple[int, int]:
    """Args:
        env: the variables `make dotenv` writes into `.env`.

    Returns:
        The held-job age in seconds from which its service warns, and from which it is critical.

    Raises:
        JobError: a threshold is absent or malformed, or the warning does not come first.
    """
    for key in (WARN_KEY, CRIT_KEY):
        if key not in env or not env[key].strip():
            raise JobError(f"{key} is not set")
    warn = parse_duration(env[WARN_KEY])
    crit = parse_duration(env[CRIT_KEY])
    if warn >= crit:
        raise JobError(f"{WARN_KEY} must be shorter than {CRIT_KEY}")
    return warn, crit


def held_job_state(age: float, warn: int, crit: int) -> int:
    """
    Args:
        age: seconds since the held job's deploy ended.
        warn: the age from which it warns.
        crit: the age from which it is critical.
    """
    if age >= crit:
        return CRIT
    return WARN if age >= warn else OK


def _line(state: int, service: str, metrics: str, text: str) -> str:
    return f'{state} "{service}" {metrics} {text}'


def local_check(
    runners: Mapping[str, str],
    held: Iterable[tuple[Job, float]],
    caches: Iterable[Mapping[str, object]],
    free: int,
    floor: int,
    warn: int,
    crit: int,
) -> list[str]:
    """Args:
        runners: every pool runner with its state, idle, busy or held.
        held: every held job with its age in seconds.
        caches: the objects `make cache-status` prints, one per cache.
        free: the free bytes on the disk the caches and the job stacks share.
        floor: the disk floor in bytes.
        warn: the held-job age from which its service warns.
        crit: the held-job age from which it is critical.

    Returns:
        One Checkmk local check line per runner, held job and cache, and one for the disk floor.
    """
    lines = [
        _line(OK, f"Runner {name}", "-", state)
        for name, state in sorted(runners.items())
    ]
    for record, age in held:
        hours = age / 3600
        lines.append(
            _line(
                held_job_state(age, warn, crit),
                f"Held job {record.id}",
                f"age={int(age)};{warn};{crit}",
                f"held on {record.runner} for {hours:.1f} h, release with "
                f"make runner-release job={record.id}",
            )
        )
    for row in caches:
        used = row["used_bytes"]
        cap = int(row["cap_bytes"])
        if used is None:
            lines.append(_line(UNKNOWN, f"Cache {row['name']}", "-", "use unknown"))
            continue
        state = CRIT if int(used) > cap else OK
        lines.append(
            _line(
                state,
                f"Cache {row['name']}",
                f"used={used};;{cap}",
                f"{int(used)} of {cap} bytes",
            )
        )
    lines.append(
        _line(
            CRIT if free < floor else OK,
            "Disk floor",
            f"free={free};;{floor}",
            f"{free} bytes free, floor {floor}",
        )
    )
    return lines
