"""The Checkmk local check of the runner pool inside the infra runner: its timer and the file Checkmk reads."""

from __future__ import annotations

from typing import TYPE_CHECKING

from utils.cache.evict import CACHES, FLOOR_KEY, IDLE_KEY
from utils.infra_tools import timer_units, unit_installs, write_units
from utils.runner.checkmk_local_check import CRIT_KEY, WARN_KEY

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

TIMER = "infinito-pool-checkmk"
TIMER_PERIOD = "1min"
CHECK_DIR = ("checkmk",)
CHECK_FILE = "pool.txt"
REQUIRED_KEYS = (
    *(spec.cap_key for spec in CACHES),
    IDLE_KEY,
    FLOOR_KEY,
    WARN_KEY,
    CRIT_KEY,
)
PATH_KEYS = tuple(spec.path_key for spec in CACHES if spec.path_key)


def check_dir(base: Path) -> Path:
    """Args:
        base: the cache base the infra runner binds at its host path.

    Returns:
        The directory the timer writes :data:`CHECK_FILE` into and
        ``web-app-checkmk`` mounts read-only.
    """
    return base.joinpath(*CHECK_DIR)


def check_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Args:
        env: the variables ``make dotenv`` writes into ``.env``.

    Returns:
        The caps, the idle window, the floor, the held-job thresholds and
        every set cache path, which the local check reads inside the runner.

    Raises:
        KeyError: a key of :data:`REQUIRED_KEYS` is unset.
    """
    return {
        **{key: env[key] for key in REQUIRED_KEYS},
        **{key: env[key] for key in PATH_KEYS if env.get(key)},
    }


def check_units(
    checkout: Path, python: str, environment: Mapping[str, str], base: Path
) -> dict[str, str]:
    """Args:
        checkout: read-only checkout root inside the runner, at its host path.
        python: interpreter of the runner image.
        environment: :func:`check_environment`.
        base: the cache base the infra runner binds at its host path.

    Returns:
        The systemd service and timer that rewrite the local check file, by file name.
    """
    target = check_dir(base) / CHECK_FILE
    return timer_units(
        TIMER,
        TIMER_PERIOD,
        "Write the Checkmk local check of the runner pool",
        checkout,
        environment,
        f"{python} -m utils.runner.checkmk_local_check {target}",
    )


def check_setup(
    argv: Sequence[str],
    unit_dir: Path,
    checkout: Path,
    python: str,
    env: Mapping[str, str],
    base: Path,
) -> list[list[str]]:
    """Args:
        argv: compose call of the infra stack.
        unit_dir: directory below the cache base the units are written into.
        checkout: read-only checkout root inside the runner, at its host path.
        python: interpreter of the runner image.
        env: the variables ``make dotenv`` writes into ``.env``.
        base: the cache base the infra runner binds at its host path.

    Returns:
        The commands that link the service and enable the timer inside the
        runner, once the units and the check directory exist.

    Raises:
        KeyError: a key of :data:`REQUIRED_KEYS` is unset.
    """
    units = check_units(checkout, python, check_environment(env), base)
    check_dir(base).mkdir(parents=True, exist_ok=True)
    write_units(unit_dir, units)
    return unit_installs(argv, unit_dir, TIMER)
