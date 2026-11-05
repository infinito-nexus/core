from __future__ import annotations

import base64
import contextlib
import json
import os
import re
import shutil
import stat
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from utils.cache.files import read_text

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping
    from typing import TextIO

DAY_SECONDS = 86400
IDLE_KEY = "INFINITO_CACHE_MAX_IDLE_DAYS"
FLOOR_KEY = "INFINITO_CACHE_DISK_FLOOR"
SHARED = "shared"
MODELS = "models"
PACKAGE = "package"
REGISTRY = "registry"
BUILD = "build"
SWEPT = (SHARED, MODELS)
SIDECAR_SUFFIXES = (".body", ".sig")
PLAYWRIGHT_METADATA = ".links"
CLEANUP_TASK = "repository.cleanup"
ASSET_BLOB_CLEANUP_TASK = "assetBlob.cleanup"
COMPACT_TASK = "blobstore.compact"
BLOBSTORE = "default"

_SIZE_RE = re.compile(r"^\s*(\d+)\s*([kmgt]?)b?\s*$", re.IGNORECASE)
_BINARY = {"": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}
_HUMAN_RE = re.compile(r"^\s*([\d.]+)\s*([kKMGTP]?)B\s*$")
_DECIMAL = {
    "": 1,
    "k": 10**3,
    "K": 10**3,
    "M": 10**6,
    "G": 10**9,
    "T": 10**12,
    "P": 10**15,
}


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


@dataclass(frozen=True)
class Unit:
    paths: tuple[Path, ...]
    size: int
    used_at: float


@dataclass(frozen=True)
class Asset:
    id: str
    size: int
    used_at: float


class NexusStore(Protocol):
    def used(self) -> int: ...

    def assets(self) -> list[Asset]: ...

    def delete(self, asset_id: str) -> None: ...

    def run(self, task_type: str) -> None: ...


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


def parse_human_size(value: str) -> int:
    """Args:
        value: a decimal size as the Docker CLI prints it, as in ``28.5GB``.

    Returns:
        The size in bytes.

    Raises:
        CacheConfigError: the value names no size.
    """
    match = _HUMAN_RE.match(value)
    if match is None:
        raise CacheConfigError(f"'{value}' is no Docker size like 28.5GB")
    return int(float(match.group(1)) * _DECIMAL[match.group(2)])


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


def _allocated(st: os.stat_result) -> int:
    return st.st_blocks * 512


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
            total += _allocated(info)
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


def _used_at(info: os.stat_result, fallback: bool) -> float:
    if fallback:
        return info.st_mtime
    return max(info.st_atime, info.st_mtime)


def _files(root: Path) -> dict[Path, os.stat_result]:
    found: dict[Path, os.stat_result] = {}
    if not root.is_dir():
        return found
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                continue
            if stat.S_ISDIR(info.st_mode):
                pending.append(Path(entry.path))
            else:
                found[Path(entry.path)] = info
    return found


def _read_keeping_atime(path: Path, info: os.stat_result) -> str:
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return ""
    with contextlib.suppress(OSError):
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns), follow_symlinks=False)
    return text


def _grouped(
    files: Mapping[Path, os.stat_result],
    links: Mapping[Path, set[Path]],
    fallback: bool,
) -> list[Unit]:
    parent: dict[Path, Path] = {path: path for path in files}

    def find(path: Path) -> Path:
        while parent[path] != path:
            parent[path] = parent[parent[path]]
            path = parent[path]
        return path

    for source, targets in links.items():
        for target in targets:
            if source in parent and target in parent:
                parent[find(target)] = find(source)
    groups: dict[Path, list[Path]] = {}
    for path in files:
        groups.setdefault(find(path), []).append(path)
    return [
        Unit(
            paths=tuple(sorted(members)),
            size=sum(_allocated(files[member]) for member in members),
            used_at=max(_used_at(files[member], fallback) for member in members),
        )
        for members in groups.values()
    ]


def _sidecar_links(files: Iterable[Path]) -> dict[Path, set[Path]]:
    present = set(files)
    links: dict[Path, set[Path]] = {}
    for path in present:
        for suffix in SIDECAR_SUFFIXES:
            if path.name.endswith(suffix):
                base = path.with_name(path.name[: -len(suffix)])
                if base in present:
                    links.setdefault(base, set()).add(path)
    return links


def _directory_unit(root: Path, fallback: bool) -> Unit:
    info = os.lstat(root)
    members = list(_files(root).values())
    size = _allocated(info) + sum(_allocated(member) for member in members)
    size += sum(_allocated(os.lstat(directory)) for directory in _directories(root))
    if members:
        used_at = max(_used_at(member, fallback) for member in members)
    else:
        used_at = info.st_mtime
    return Unit(paths=(root,), size=size, used_at=used_at)


def _directories(root: Path) -> list[Path]:
    found: list[Path] = []
    pending = [root]
    while pending:
        current = pending.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            if entry.is_dir(follow_symlinks=False):
                found.append(Path(entry.path))
                pending.append(Path(entry.path))
    return found


def _integrity_paths(cacache: Path, integrity: str) -> set[Path]:
    paths: set[Path] = set()
    for token in integrity.split():
        algorithm, _, digest = token.partition("-")
        if not digest:
            continue
        try:
            hexdigest = base64.b64decode(digest.split("?")[0]).hex()
        except ValueError:
            continue
        paths.add(
            cacache
            / "content-v2"
            / algorithm
            / hexdigest[:2]
            / hexdigest[2:4]
            / hexdigest[4:]
        )
    return paths


def _npm_links(
    cacache: Path, files: Mapping[Path, os.stat_result]
) -> dict[Path, set[Path]]:
    index = cacache / "index-v5"
    links: dict[Path, set[Path]] = {}
    for path, info in files.items():
        if not path.is_relative_to(index):
            continue
        for line in _read_keeping_atime(path, info).splitlines():
            _, _, payload = line.partition("\t")
            try:
                entry = json.loads(payload)
            except ValueError:
                continue
            integrity = entry.get("integrity") if isinstance(entry, dict) else None
            if isinstance(integrity, str):
                links.setdefault(path, set()).update(
                    _integrity_paths(cacache, integrity)
                )
    return links


def _ollama_links(
    root: Path, files: Mapping[Path, os.stat_result]
) -> dict[Path, set[Path]]:
    manifests = root / "manifests"
    links: dict[Path, set[Path]] = {}
    for path, info in files.items():
        if not path.is_relative_to(manifests):
            continue
        try:
            manifest = json.loads(_read_keeping_atime(path, info))
        except ValueError:
            continue
        if not isinstance(manifest, dict):
            continue
        layers = [manifest.get("config"), *(manifest.get("layers") or [])]
        for layer in layers:
            digest = layer.get("digest") if isinstance(layer, dict) else None
            if isinstance(digest, str):
                links.setdefault(path, set()).add(
                    root / "blobs" / digest.replace(":", "-")
                )
    return links


def shared_units(root: Path, fallback: bool) -> list[Unit]:
    """Args:
        root: the shared cache folder (pip, npm, pacman, ms-playwright and the rest).
        fallback: True when access times are unreliable and modification times count.

    Returns:
        Every unit the sweeper may remove as a whole.
    """
    files = _files(root)
    links = _sidecar_links(files)
    playwright = root / "ms-playwright"
    units: list[Unit] = []
    if playwright.is_dir():
        for child in sorted(playwright.iterdir()):
            if child.is_dir() and not child.is_symlink():
                for path in [path for path in files if path.is_relative_to(child)]:
                    del files[path]
                if child.name != PLAYWRIGHT_METADATA:
                    units.append(_directory_unit(child, fallback))
    cacache = root / "npm" / "_cacache"
    if cacache.is_dir():
        for source, targets in _npm_links(cacache, files).items():
            links.setdefault(source, set()).update(targets)
    units.extend(_grouped(files, links, fallback))
    return units


def model_units(root: Path, fallback: bool) -> list[Unit]:
    """Args:
        root: the models folder of the tools lane.
        fallback: True when access times are unreliable and modification times count.

    Returns:
        One unit per model: a package directory or file below a tool's folder, or an
        Ollama manifest together with the blobs no other manifest references.
    """
    units: list[Unit] = []
    if not root.is_dir():
        return units
    for tool in sorted(root.iterdir()):
        if tool.is_symlink() or not tool.is_dir():
            info = os.lstat(tool)
            units.append(
                Unit(
                    paths=(tool,),
                    size=_allocated(info),
                    used_at=_used_at(info, fallback),
                )
            )
        elif (tool / "manifests").is_dir() and (tool / "blobs").is_dir():
            files = _files(tool)
            units.extend(_grouped(files, _ollama_links(tool, files), fallback))
        else:
            for model in sorted(tool.iterdir()):
                if model.is_dir() and not model.is_symlink():
                    units.append(_directory_unit(model, fallback))
                else:
                    info = os.lstat(model)
                    units.append(
                        Unit(
                            paths=(model,),
                            size=_allocated(info),
                            used_at=_used_at(info, fallback),
                        )
                    )
    return units


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
    candidate = path.parent.resolve() / path.name
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


def _timestamp(value: object) -> float:
    if not isinstance(value, str) or not value:
        return 0.0
    try:
        return datetime.fromisoformat(value).timestamp()
    except ValueError:
        return 0.0


class NexusRest:
    def __init__(
        self,
        base: str,
        user: str,
        password: str,
        poll_seconds: float,
        timeout_seconds: float,
    ) -> None:
        """
        Args:
            base: the REST root, as in ``http://127.0.0.1:8081/service/rest``.
            user: the admin user.
            password: its password.
            poll_seconds: the pause between two task state reads.
            timeout_seconds: how long one task may run before the eviction gives up.
        """
        self.base = base.rstrip("/")
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds

    def _call(self, method: str, path: str, query: Mapping[str, str]) -> object:
        url = f"{self.base}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(url, method=method, headers=self.headers)  # noqa: S310
        with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
            body = response.read()
        return json.loads(body) if body else None

    def reachable(self) -> bool:
        try:
            self._call("GET", "/v1/status", {})
        except (OSError, ValueError):
            return False
        return True

    def used(self) -> int:
        for store in self._call("GET", "/v1/blobstores", {}) or []:
            if store.get("name") == BLOBSTORE:
                return int(store.get("totalSizeInBytes") or 0)
        raise LookupError(f"Nexus has no blob store named {BLOBSTORE}")

    def _pages(self, path: str, query: Mapping[str, str]) -> list[dict]:
        items: list[dict] = []
        token = ""
        while True:
            page = self._call(
                "GET", path, {**query, "continuationToken": token} if token else query
            )
            items.extend(page.get("items") or [])
            token = page.get("continuationToken") or ""
            if not token:
                return items

    def assets(self) -> list[Asset]:
        found: list[Asset] = []
        for repository in self._call("GET", "/v1/repositories", {}) or []:
            if repository.get("type") != "proxy":
                continue
            found.extend(
                Asset(
                    id=item["id"],
                    size=int(item.get("fileSize") or 0),
                    used_at=_timestamp(item.get("lastDownloaded"))
                    or _timestamp(item.get("blobCreated")),
                )
                for item in self._pages(
                    "/v1/assets", {"repository": repository["name"]}
                )
            )
        return found

    def delete(self, asset_id: str) -> None:
        self._call("DELETE", f"/v1/assets/{urllib.parse.quote(asset_id, safe='')}", {})

    def run(self, task_type: str) -> None:
        tasks = self._pages("/v1/tasks", {"type": task_type})
        if not tasks:
            raise LookupError(
                f"Nexus has no {task_type} task; run the package cache bootstrap"
            )
        for task in tasks:
            previous = task.get("lastRun")
            self._call("POST", f"/v1/tasks/{task['id']}/run", {})
            deadline = time.monotonic() + self.timeout_seconds
            while True:
                state = self._call("GET", f"/v1/tasks/{task['id']}", {}) or {}
                if (
                    state.get("currentState") == "WAITING"
                    and state.get("lastRun") != previous
                ):
                    break
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"Nexus task {task_type} did not finish in {self.timeout_seconds}s"
                    )
                time.sleep(self.poll_seconds)


def nexus_from_env(
    env: Mapping[str, str], poll_seconds: float, timeout_seconds: float
) -> NexusRest | None:
    """Args:
        env: the variables of `.env`.
        poll_seconds: the pause between two task state reads.
        timeout_seconds: how long one task may run.

    Returns:
        A client of the dev stack's Nexus, or None when it does not answer.
    """
    host = env.get("INFINITO_CACHE_PACKAGE_REST_HOST", "").strip()
    port = env.get("INFINITO_CACHE_PACKAGE_PORT", "").strip()
    password = env.get("INFINITO_CACHE_PACKAGE_ADMIN_PASSWORD", "").strip()
    if not host or not port or not password:
        return None
    client = NexusRest(
        f"http://{host}:{port}/service/rest",
        "admin",
        password,
        poll_seconds,
        timeout_seconds,
    )
    return client if client.reachable() else None


def run_command(command: list[str]) -> str | None:
    """Args:
        command: the argv to run.

    Returns:
        Its stdout, or None when it cannot start, times out or exits non-zero.
    """
    try:
        done = subprocess.run(
            command, capture_output=True, text=True, check=False, timeout=300
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def build_cache_usage(run: Callable[[list[str]], str | None]) -> Usage:
    """Args:
        run: runs a command and returns its stdout, or None when it fails.

    Returns:
        The size of the host Docker build cache; ``used`` is None without a reachable engine.
    """
    output = run(["docker", "system", "df", "--format", "{{json .}}"])
    if output is None:
        return Usage(used=None, complete=False)
    for line in output.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("Type") == "Build Cache":
            try:
                return Usage(
                    used=parse_human_size(str(row.get("Size", ""))), complete=True
                )
            except CacheConfigError:
                return Usage(used=None, complete=False)
    return Usage(used=0, complete=True)


def tools_running(run: Callable[[list[str]], str | None], models: Path) -> bool | None:
    """Args:
        run: runs a command and returns its stdout, or None when it fails.
        models: the models folder the tools lane mounts at the same path.

    Returns:
        Whether a running container mounts the models folder; None when the engine cannot tell.
    """
    output = run(["docker", "ps", "--quiet", "--filter", f"volume={models}"])
    if output is None:
        return None
    return bool(output.strip())


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


def evict(
    settings: Settings,
    measured: Mapping[str, Usage],
    free: int,
    now: float,
    tools: Callable[[Path], bool | None],
    nexus: Callable[[], NexusStore | None],
    out: TextIO,
) -> int:
    """Args:
        settings: the caches with their paths, caps, the idle window and the floor.
        measured: the usage of every cache before the eviction.
        free: the free bytes on the cache filesystems.
        now: the current time in seconds since the epoch.
        tools: tells whether a tools service runs on the models folder, None when unknown.
        nexus: opens the Nexus blob store, None when it does not answer.
        out: where the report goes.

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
        if running is False:
            fallback = atime_fallback(models.path)
            failed += sweep(
                models.path,
                model_units(models.path, fallback),
                models.cap,
                now,
                settings.idle_seconds,
                out,
            )
        else:
            print(
                f"[cache-evict] {models.path}: skipped, a tools service may hold the models",
                file=out,
            )
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
