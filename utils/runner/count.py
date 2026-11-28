from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils import PROJECT_ROOT
from utils.cache.evict import CacheConfigError, parse_size
from utils.cache.yaml import load_yaml_any

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from pathlib import Path

COUNT_KEY = "INFINITO_RUNNER_COUNT"
FLOOR_KEY = "INFINITO_CACHE_DISK_FLOOR"
CALIBRATION = PROJECT_ROOT / "inventories" / "development" / "runner-calibration.yml"
RECORD_KEYS = ("applications", "commit", "date", "peak_memory", "cpus", "disk_growth")

_COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
_MEMTOTAL = re.compile(r"^MemTotal:\s+(\d+)\s+kB$", re.MULTILINE)


class CountError(ValueError):
    pass


@dataclass(frozen=True)
class Budget:
    ram: int
    cpus: float
    disk: int


@dataclass(frozen=True)
class Host:
    ram: int
    cpus: int
    free: int


def _size(value: object) -> int:
    try:
        return parse_size(str(value))
    except CacheConfigError as exc:
        raise CountError(str(exc)) from exc


def _size_problem(record: Mapping[str, object], key: str) -> str | None:
    try:
        size = _size(record[key])
    except CountError as exc:
        return f"{key}: {exc}"
    return None if size > 0 else f"{key} must be above zero"


def record_problems(record: object) -> list[str]:
    """Args:
        record: the parsed calibration file.

    Returns:
        One problem per missing or malformed field of the measured deploy the budgets come from.
    """
    if not isinstance(record, dict):
        return ["the calibration holds no mapping"]
    missing = [
        f"{key} is missing" for key in RECORD_KEYS if record.get(key) in (None, "", [])
    ]
    if missing:
        return missing
    problems: list[str] = []
    applications = record["applications"]
    if not isinstance(applications, list) or not all(
        isinstance(app, str) and app for app in applications
    ):
        problems.append("applications must list the deployed application ids")
    if not _COMMIT.match(str(record["commit"])):
        problems.append("commit must be the measured commit's hexadecimal sha")
    try:
        dt.date.fromisoformat(str(record["date"]))
    except ValueError:
        problems.append("date must be an ISO date like 2026-11-07")
    problems.extend(
        problem
        for key in ("peak_memory", "disk_growth")
        if (problem := _size_problem(record, key))
    )
    try:
        if float(str(record["cpus"])) <= 0:
            problems.append("cpus must be above zero")
    except ValueError:
        problems.append("cpus must be a number of CPUs")
    return problems


def load_budget(path: Path) -> Budget | None:
    """Args:
        path: the calibration file.

    Returns:
        What one full deploy takes, None when no calibration is recorded yet.

    Raises:
        CountError: the file does not record the measured deploy.
    """
    if not path.is_file():
        return None
    record = load_yaml_any(str(path))
    problems = record_problems(record)
    if problems:
        raise CountError(f"{path}: " + "; ".join(problems))
    return Budget(
        ram=_size(record["peak_memory"]),
        cpus=float(str(record["cpus"])),
        disk=_size(record["disk_growth"]),
    )


def growth(rows: Iterable[Mapping[str, object]]) -> int:
    """Args:
        rows: the objects `make cache-status` prints, one per cache.

    Returns:
        The bytes the caches may still grow, the sum of ``max(0, cap - used)``;
        a cache whose use is unknown counts with its whole cap.
    """
    return sum(
        max(0, int(row["cap_bytes"]) - int(row["used_bytes"] or 0)) for row in rows
    )


def _env(env: Mapping[str, str], key: str) -> str:
    if key not in env:
        raise CountError(f"{key} is not set; run 'make dotenv'")
    return env[key].strip()


def override(env: Mapping[str, str]) -> int | None:
    """Args:
        env: the variables `make dotenv` writes into `.env`.

    Returns:
        The runner count the environment pins, None when it leaves it to the host.

    Raises:
        CountError: the key is absent or holds no whole number of at least 1.
    """
    raw = _env(env, COUNT_KEY)
    if not raw:
        return None
    if not raw.isdigit() or int(raw) < 1:
        raise CountError(
            f"{COUNT_KEY} must be a whole number of at least 1, got '{raw}'"
        )
    return int(raw)


def floor(env: Mapping[str, str]) -> int:
    """Args:
        env: the variables `make dotenv` writes into `.env`.

    Raises:
        CountError: the floor is absent or malformed.
    """
    raw = _env(env, FLOOR_KEY)
    if not raw:
        raise CountError(f"{FLOOR_KEY} is not set")
    return _size(raw)


def report(
    host: Host, budget: Budget | None, grown: int, floor_bytes: int, pinned: int | None
) -> dict[str, object]:
    """Args:
        host: total RAM, CPUs and free disk of the machine.
        budget: what one full deploy takes, None when no calibration is recorded.
        grown: the remaining cache growth, see :func:`growth`.
        floor_bytes: the disk floor.
        pinned: the override, None for none.

    Returns:
        The runner count and the RAM, CPU and disk terms it is the minimum of.

    Raises:
        CountError: neither a calibration nor an override decides the count.
    """
    if budget is None and pinned is None:
        raise CountError(
            f"{CALIBRATION} does not exist and {COUNT_KEY} is empty; "
            "measure a full deploy and record it there, or set the count"
        )
    terms = None
    derived = None
    if budget is not None:
        disk = host.free - grown - floor_bytes
        terms = {
            "ram": host.ram // budget.ram,
            "cpu": int(host.cpus // budget.cpus),
            "disk": max(0, disk) // budget.disk,
        }
        derived = max(1, min(terms.values()))
    return {
        "count": pinned if pinned is not None else derived,
        "derived": derived,
        "override": pinned,
        "terms": terms,
        "host": {"ram_bytes": host.ram, "cpus": host.cpus, "free_bytes": host.free},
        "budget": None
        if budget is None
        else {"ram_bytes": budget.ram, "cpus": budget.cpus, "disk_bytes": budget.disk},
        "growth_bytes": grown,
        "floor_bytes": floor_bytes,
    }


def total_ram(meminfo: str) -> int:
    """Args:
        meminfo: the content of ``/proc/meminfo``.

    Raises:
        CountError: it names no ``MemTotal``.
    """
    match = _MEMTOTAL.search(meminfo)
    if match is None:
        raise CountError("/proc/meminfo names no MemTotal")
    return int(match[1]) * 1024
