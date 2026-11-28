from __future__ import annotations

import os
import re
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.eviction.units import allocated, model_units, shared_units

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from typing import TextIO

    from utils.cache.eviction.nexus import NexusStore
    from utils.cache.eviction.units import Unit

DAY_SECONDS = 86400
IDLE_KEY = "INFINITO_CACHE_MAX_IDLE_DAYS"
FLOOR_KEY = "INFINITO_CACHE_DISK_FLOOR"
SHARED = "shared"
MODELS = "models"
PACKAGE = "package"
REGISTRY = "registry"
BUILD = "build"
SWEPT = (SHARED, MODELS)
CLEANUP_TASK = "repository.cleanup"
ASSET_BLOB_CLEANUP_TASK = "assetBlob.cleanup"
COMPACT_TASK = "blobstore.compact"

_SIZE_RE = re.compile(r"^\s*(\d+)\s*([kmgt]?)b?\s*$", re.IGNORECASE)
_BINARY = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


@dataclass(frozen=True)
class CacheSpec:
    name: str
    path_key: str | None
    cap_key: str


CACHES: tuple[CacheSpec, ...] = (
    CacheSpec(
        REGISTRY,
        "INFINITO_CACHE_REGISTRY_HOST_PATH",
        "INFINITO_CACHE_REGISTRY_MAX_SIZE",
    ),
    CacheSpec(
        PACKAGE,
        "INFINITO_CACHE_PACKAGE_HOST_PATH",
        "INFINITO_CACHE_PACKAGE_BLOBSTORE_MAX",
    ),
    CacheSpec(
        SHARED, "INFINITO_CACHE_SHARED_HOST_PATH", "INFINITO_CACHE_SHARED_MAX_SIZE"
    ),
    CacheSpec(
        MODELS, "INFINITO_TOOLS_MODELS_HOST_PATH", "INFINITO_TOOLS_MODELS_MAX_SIZE"
    ),
    CacheSpec(BUILD, None, "INFINITO_BUILD_CACHE_MAX_SIZE"),
)


class CacheConfigError(ValueError):
    pass


class OutsideCacheError(ValueError):
    pass


@dataclass(frozen=True)
class Cache:
    name: str
    path: Path | None
    cap_key: str
    cap: int


@dataclass(frozen=True)
class Settings:
    caches: tuple[Cache, ...]
    idle_seconds: int
    floor: int

    def cache(self, name: str) -> Cache:
        return next(cache for cache in self.caches if cache.name == name)


@dataclass(frozen=True)
class Usage:
    used: int | None
    complete: bool


def parse_size(value: str) -> int:
    """Args:
        value: digits with an optional binary unit k, m, g or t, as in ``40g``.

    Returns:
        The size in bytes.

    Raises:
        CacheConfigError: the value names no size.
    """
    match = _SIZE_RE.match(value)
    if match is None:
        raise CacheConfigError(f"'{value}' is no size like 40g")
    return int(match.group(1)) * _BINARY[match.group(2).lower()]


def _required(env: Mapping[str, str], key: str) -> str:
    value = env.get(key, "").strip()
    if not value:
        raise CacheConfigError(f"{key} is not set")
    return value


def load_settings(env: Mapping[str, str]) -> Settings:
    """Args:
        env: the variables `make dotenv` writes into `.env`.

    Raises:
        CacheConfigError: a cap, the idle window or the floor is missing or malformed.
    """
    caches = []
    for spec in CACHES:
        raw = env.get(spec.path_key, "").strip() if spec.path_key else ""
        caches.append(
            Cache(
                name=spec.name,
                path=Path(raw) if raw else None,
                cap_key=spec.cap_key,
                cap=parse_size(_required(env, spec.cap_key)),
            )
        )
    idle = _required(env, IDLE_KEY)
    if not idle.isdigit() or int(idle) < 1:
        raise CacheConfigError(
            f"{IDLE_KEY} must be a positive number of days, got '{idle}'"
        )
    return Settings(
        caches=tuple(caches),
        idle_seconds=int(idle) * DAY_SECONDS,
        floor=parse_size(_required(env, FLOOR_KEY)),
    )


def _existing(path: Path) -> Path:
    current = path
    while not current.exists() and current != current.parent:
        current = current.parent
    return current


def measure(root: Path) -> Usage:
    """Args:
        root: a cache directory.

    Returns:
        The bytes allocated below it, and whether every entry was readable.
    """
    if not root.exists():
        return Usage(used=0, complete=True)
    total = 0
    complete = True
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            complete = False
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                complete = False
                continue
            total += allocated(info)
            if stat.S_ISDIR(info.st_mode):
                pending.append(Path(entry.path))
    return Usage(used=total, complete=complete)


def atime_fallback(path: Path) -> bool:
    """Args:
        path: a cache directory, or a path below one that does not exist yet.

    Returns:
        True when its filesystem is mounted noatime, so the sweeper reads modification times.
    """
    return bool(os.statvfs(_existing(path)).f_flag & os.ST_NOATIME)


def free_bytes(paths: Iterable[Path]) -> int:
    """
    Args:
        paths: the cache directories; each filesystem they live on counts once.
    """
    seen: dict[int, int] = {}
    for path in paths:
        anchor = _existing(path)
        device = anchor.stat().st_dev
        if device not in seen:
            vfs = os.statvfs(anchor)
            seen[device] = vfs.f_bavail * vfs.f_frsize
    return sum(seen.values())


def plan(
    units: Iterable[Unit], total: int, cap: int, now: float, idle_seconds: int
) -> list[Unit]:
    """Args:
        units: every removable unit of one cache.
        total: the bytes the cache holds now.
        cap: the bytes it may hold.
        now: the current time in seconds since the epoch.
        idle_seconds: the idle window.

    Returns:
        The idle units, then the least recently used ones until the cache fits its cap.
    """
    stale = [unit for unit in units if now - unit.used_at > idle_seconds]
    fresh = sorted(
        (unit for unit in units if now - unit.used_at <= idle_seconds),
        key=lambda unit: unit.used_at,
    )
    remaining = total - sum(unit.size for unit in stale)
    chosen = list(stale)
    for unit in fresh:
        if remaining <= cap:
            break
        chosen.append(unit)
        remaining -= unit.size
    return chosen


def _inside(path: Path, root: Path) -> bool:
    anchor = root.resolve()
    candidate = Path(os.path.normpath(path.parent.resolve() / path.name))
    return candidate != anchor and candidate.is_relative_to(anchor)


def remove(unit: Unit, root: Path) -> None:
    """Args:
        unit: the unit to delete, every path of it at once.
        root: the cache directory the unit belongs to.

    Raises:
        OutsideCacheError: a path of the unit lies outside the cache directory or is the directory itself.
    """
    for path in unit.paths:
        if not _inside(path, root):
            raise OutsideCacheError(f"{path} is not inside the cache {root}")
    for path in unit.paths:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            continue
        if stat.S_ISDIR(info.st_mode):
            shutil.rmtree(path)
        else:
            path.unlink()


def sweep(
    root: Path, units: list[Unit], cap: int, now: float, idle_seconds: int, out: TextIO
) -> int:
    """Args:
        root: the cache directory.
        units: its removable units.
        cap: the bytes it may hold.
        now: the current time in seconds since the epoch.
        idle_seconds: the idle window.
        out: where the report goes.

    Returns:
        The number of units that could not be removed.
    """
    total = measure(root).used or 0
    failed = 0
    for unit in plan(units, total, cap, now, idle_seconds):
        try:
            remove(unit, root)
        except OSError as exc:
            failed += 1
            print(f"[cache-evict] could not remove {unit.paths[0]}: {exc}", file=out)
    return failed


def evict_package(store: NexusStore, cap: int) -> tuple[int, int]:
    """Args:
        store: the Nexus blob store and the tasks that clean and compact it.
        cap: the bytes the blob store may hold.

    Returns:
        The blob store size before and after the eviction.
    """
    store.run(CLEANUP_TASK)
    store.run(ASSET_BLOB_CLEANUP_TASK)
    store.run(COMPACT_TASK)
    before = store.used()
    used = before
    while used > cap:
        assets = sorted(store.assets(), key=lambda asset: asset.used_at)
        if not assets:
            break
        excess = used - cap
        freed = 0
        for asset in assets:
            if freed >= excess:
                break
            store.delete(asset.id)
            freed += asset.size
        store.run(ASSET_BLOB_CLEANUP_TASK)
        store.run(COMPACT_TASK)
        shrunk = store.used()
        if shrunk >= used:
            used = shrunk
            break
        used = shrunk
    return before, used


def usages(settings: Settings, build: Usage) -> dict[str, Usage]:
    """
    Args:
        settings: the caches with their paths and caps.
        build: the measured host build cache.
    """
    found = {BUILD: build}
    for cache in settings.caches:
        if cache.name != BUILD:
            found[cache.name] = (
                measure(cache.path) if cache.path else Usage(used=0, complete=True)
            )
    return found


def floor_violation(
    settings: Settings, measured: Mapping[str, Usage], free: int
) -> list[str]:
    """Args:
        settings: the caches with their caps, and the disk floor.
        measured: the usage of every cache.
        free: the free bytes on the cache filesystems.

    Returns:
        The refusal, one line each, or nothing when the caps leave the floor free.
    """
    used = sum(usage.used or 0 for usage in measured.values())
    caps = sum(cache.cap for cache in settings.caches)
    margin = free + used - caps
    if margin >= settings.floor:
        return []
    return [
        f"[cache-evict] free {free} + used {used} - caps {caps} = {margin} bytes is below {FLOOR_KEY} ({settings.floor} bytes)",
        "[cache-evict] lower one of these caps or free disk space:",
        *(
            f"[cache-evict]   {cache.cap_key} ({cache.cap} bytes)"
            for cache in settings.caches
        ),
    ]


def status(
    settings: Settings, measured: Mapping[str, Usage]
) -> list[dict[str, object]]:
    """Args:
        settings: the caches with their paths and caps.
        measured: the usage of every cache.

    Returns:
        One JSON-ready object per cache.
    """
    rows: list[dict[str, object]] = []
    for cache in settings.caches:
        usage = measured[cache.name]
        swept = cache.name in SWEPT and cache.path is not None
        rows.append(
            {
                "name": cache.name,
                "path": str(cache.path) if cache.path else None,
                "used_bytes": usage.used,
                "cap_bytes": cache.cap,
                "headroom_bytes": cache.cap - usage.used
                if usage.used is not None
                else None,
                "cap_variable": cache.cap_key,
                "atime_fallback": atime_fallback(cache.path) if swept else False,
                "complete": usage.complete,
            }
        )
    return rows


def _stored(unit: Unit, root: Path, digests: frozenset[str]) -> bool:
    (path, *rest) = unit.paths
    return not rest and path.parent == root and path.name in digests


def evict(
    settings: Settings,
    measured: Mapping[str, Usage],
    free: int,
    now: float,
    tools: Callable[[Path], bool | None],
    nexus: Callable[[], NexusStore | None],
    out: TextIO,
    declared: Callable[[], frozenset[str] | None],
) -> int:
    """Args:
        settings: the caches with their paths, caps, the idle window and the floor.
        measured: the usage of every cache before the eviction.
        free: the free bytes on the cache filesystems.
        now: the current time in seconds since the epoch.
        tools: tells whether a tools service runs on the models folder, None when unknown.
        nexus: opens the Nexus blob store, None when it does not answer.
        out: where the report goes.
        declared: the sha256 of every artefact a role still declares, whose
            store entry ``<models>/<sha256>`` the sweep keeps; None when unknown.

    Returns:
        The exit code: 1 on a floor violation, an unremovable unit, or a blob store
        left above its cap or without its tasks, else 0.
    """
    refusal = floor_violation(settings, measured, free)
    if refusal:
        print("\n".join(refusal), file=out)
        return 1
    failed = 0
    shared = settings.cache(SHARED)
    if shared.path is not None and shared.path.is_dir():
        fallback = atime_fallback(shared.path)
        failed += sweep(
            shared.path,
            shared_units(shared.path, fallback),
            shared.cap,
            now,
            settings.idle_seconds,
            out,
        )
    models = settings.cache(MODELS)
    if models.path is not None and models.path.is_dir():
        running = tools(models.path)
        digests = declared() if running is False else None
        if digests is not None:
            fallback = atime_fallback(models.path)
            failed += sweep(
                models.path,
                [
                    unit
                    for unit in model_units(models.path, fallback)
                    if not _stored(unit, models.path, digests)
                ],
                models.cap,
                now,
                settings.idle_seconds,
                out,
            )
        else:
            reason = (
                "the declared artefacts are unknown"
                if running is False
                else "a tools service may hold the models"
            )
            print(f"[cache-evict] {models.path}: skipped, {reason}", file=out)
    package = settings.cache(PACKAGE)
    store = nexus()
    if store is None:
        print("[cache-evict] package: skipped, Nexus does not answer", file=out)
    else:
        try:
            before, after = evict_package(store, package.cap)
        except (LookupError, TimeoutError, OSError) as exc:
            failed += 1
            print(f"[cache-evict] package: {exc}", file=out)
        else:
            if after > package.cap:
                failed += 1
            print(
                f"[cache-evict] package: blob store {before} -> {after} bytes, cap {package.cap}",
                file=out,
            )
    return 1 if failed else 0
