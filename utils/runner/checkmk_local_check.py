from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.evict import (
    CacheConfigError,
    free_bytes,
    load_settings,
    status,
    usages,
)
from utils.cache.eviction.docker import build_cache_usage, run_command
from utils.runner.jobs import (
    FAILED,
    JobError,
    cleanup_report,
    parse_duration,
    queue_root,
    runners,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from utils.cache.evict import Usage
    from utils.runner.jobs import Job

OK = 0
WARN = 1
CRIT = 2
UNKNOWN = 3
WARN_KEY = "INFINITO_HELD_JOB_WARN_AGE"
CRIT_KEY = "INFINITO_HELD_JOB_CRIT_AGE"
SECTION = "<<<local:sep(0)>>>"
FILE_MODE = 0o644
POOL_SERVICE = "Runner pool"


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
        runners: every pool runner with its state, idle, busy, held or failed.
        held: every held job with its age in seconds.
        caches: the objects `make cache-status` prints, one per cache.
        free: the free bytes on the disk the caches and the job stacks share.
        floor: the disk floor in bytes.
        warn: the held-job age from which its service warns.
        crit: the held-job age from which it is critical.

    Returns:
        One Checkmk local check line per runner, held job and cache, and one
        for the disk floor; a failed runner, which claims no job, is critical.
    """
    lines = [
        _line(CRIT if state == FAILED else OK, f"Runner {name}", "-", state)
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


def collect(env: Mapping[str, str], root: Path, now: float, build: Usage) -> list[str]:
    """Args:
        env: the caps, cache paths, idle window, floor and held-job thresholds.
        root: the queue directory.
        now: the current time.
        build: the measured build cache of the daemon the caches run on.

    Returns:
        The lines of :func:`local_check` for the queue and the caches as they are now.

    Raises:
        JobError: a held-job threshold is absent or malformed.
        CacheConfigError: a cap, the idle window or the floor is absent or malformed.
    """
    warn, crit = thresholds(env)
    settings = load_settings(env)
    held, _stacks = cleanup_report(root, (), now)
    paths = [cache.path for cache in settings.caches if cache.path is not None]
    return local_check(
        runners(root),
        held,
        status(settings, usages(settings, build)),
        free_bytes(paths),
        settings.floor,
        warn,
        crit,
    )


def section(lines: Iterable[str]) -> str:
    """Args:
        lines: Checkmk local check lines.

    Returns:
        The agent section a datasource program prints for them.
    """
    return "\n".join((SECTION, *lines)) + "\n"


def write(target: Path, text: str) -> None:
    """Args:
    target: the file the Checkmk datasource program prints, replaced whole
        so it never reads half a section.
    text: the section.
    """
    staged = target.with_name(f".{target.name}.tmp")
    staged.write_text(text, encoding="utf-8")
    staged.chmod(FILE_MODE)
    staged.replace(target)


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "usage: python -m utils.runner.checkmk_local_check <target>",
            file=sys.stderr,
        )
        return 2
    try:
        lines = collect(
            os.environ, queue_root(), time.time(), build_cache_usage(run_command)
        )
    except (JobError, CacheConfigError) as exc:
        lines = [_line(UNKNOWN, POOL_SERVICE, "-", str(exc))]
    write(Path(sys.argv[1]), section(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
