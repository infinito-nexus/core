from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.apt_sources import (
    apt_targets,
    archive_of,
    list_file,
    sources_file,
    strip_list,
    strip_sources,
)
from utils.cache.hosts import declarations
from utils.env.handlers.infinito.cache.host.pacman_path import ARCH_HOST_ID, host_id
from utils.paths import read_group_path

if TYPE_CHECKING:
    from collections.abc import Callable

    from utils.cache.apt_sources import Claims, Targets
    from utils.cache.hosts import Declarations

    Runner = Callable[[list[str]], subprocess.CompletedProcess[str]]

APT_HOST_IDS = frozenset({"debian", "ubuntu"})
OS_RELEASE = Path("etc/os-release")
OPTIONS = "[options]"
PACMAN_CONF = Path("etc/pacman.conf")
PACMAN_DEFAULT_CACHE = "/var/cache/pacman/pkg/"
SHARED_PACMAN = "pacman"
SOURCES_LIST = Path("etc/apt/sources.list")
SOURCE_PARTS = Path("etc/apt/sources.list.d")
DEB822_SUFFIX = ".sources"
MODERNIZED_SUFFIX = ".bak"
APT_DROP_IN = Path("etc/apt/apt.conf.d/99infinito-cache-host-sync")
APT_DROP_IN_TEXT = 'APT::Keep-Downloaded-Packages "false";\n'
APT_UPDATE_STRICT = "APT::Update::Error-Mode=any"
STATE = "cache-host-sync"
MANIFEST = "manifest.json"
ENCODING = "utf-8"
ERRORS = "surrogateescape"
CACHE_DIR = re.compile(r"^\s*CacheDir\s*=\s*(?P<dir>\S+)")
SECTION = re.compile(r"^\s*\[[^\]]+\]\s*$")


class HostSyncError(Exception):
    pass


@dataclass
class Plan:
    changes: dict[Path, str] = field(default_factory=dict)
    entries: list[str] = field(default_factory=list)
    stanzas: list[str] = field(default_factory=list)
    copies: list[str] = field(default_factory=list)


def _encode(text: str) -> bytes:
    return text.encode(ENCODING, ERRORS)


def _read(path: Path) -> str | None:
    return path.read_bytes().decode(ENCODING, ERRORS) if path.is_file() else None


def _digest(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, capture_output=True, text=True, check=False)


def _tail(result: subprocess.CompletedProcess[str]) -> str:
    return " ".join((result.stderr or result.stdout).strip().splitlines()[-3:])


def shared_folder(shared: str) -> str:
    """Return the folder the stack's pacman publishes its downloads into.

    Args:
        shared: ``INFINITO_CACHE_SHARED_HOST_PATH``.

    Returns:
        ``<shared>/pacman/``, as ``scripts/docker/cache/pacman.sh`` lists it.
    """
    return f"{shared.rstrip('/')}/{SHARED_PACMAN}/"


def _dir(line: str) -> str:
    return CACHE_DIR.match(line)["dir"].rstrip("/") + "/"


def pacman_conf(text: str, shared: str) -> str:
    """Return the host's pacman.conf with the shared pacman folder as a cache.

    Args:
        text: the host's pacman.conf.
        shared: ``INFINITO_CACHE_SHARED_HOST_PATH``.

    Returns:
        *text* with ``CacheDir = <shared>/pacman/`` inserted after the last
        ``CacheDir`` of ``[options]``, and the default cache listed before it
        where ``[options]`` lists none; *text* itself where the folder is
        listed already.

    Raises:
        HostSyncError: *text* has no ``[options]`` section.
    """
    folder = shared_folder(shared)
    lines = text.splitlines(keepends=True)
    start = next((i for i, line in enumerate(lines) if line.strip() == OPTIONS), None)
    if start is None:
        raise HostSyncError(
            "pacman.conf has no [options] section to list a CacheDir in"
        )
    end = next(
        (i for i in range(start + 1, len(lines)) if SECTION.match(lines[i])),
        len(lines),
    )
    listed = [i for i in range(start + 1, end) if CACHE_DIR.match(lines[i])]
    if any(_dir(lines[i]) == folder for i in listed):
        return text
    at = (listed[-1] if listed else start) + 1
    added = [] if listed else [f"CacheDir = {PACMAN_DEFAULT_CACHE}\n"]
    added.append(f"CacheDir = {folder}\n")
    head = lines[:at]
    if not head[-1].endswith("\n"):
        head[-1] += "\n"
    return "".join([*head, *added, *lines[at:]])


def _source_files(root: Path) -> list[Path]:
    parts = root / SOURCE_PARTS
    files = sorted([*parts.glob("*.list"), *parts.glob(f"*{DEB822_SUFFIX}")])
    return [root / SOURCES_LIST, *files]


def _apt_files(root: Path) -> list[Path]:
    parts = root / SOURCE_PARTS
    modernized = sorted(parts.glob(f"*.list{MODERNIZED_SUFFIX}"))
    listed = [*_source_files(root), root / f"{SOURCES_LIST}{MODERNIZED_SUFFIX}"]
    return [path for path in [*listed, *modernized] if path.is_file()]


def apt_plan(root: Path, targets: Targets) -> Plan:
    """Plan the apt files pointing the host's sources at Nexus.

    Args:
        root: the filesystem root the host's files live under.
        targets: what ``apt_targets`` returns.

    Returns:
        The new content per changed source file, the drop-in that keeps no
        downloaded package once any source points at Nexus, and the inserted
        entries and stanzas.
    """
    plan = Plan()
    claims: Claims = {}
    for path in _source_files(root):
        text = _read(path)
        if text is None:
            continue
        deb822 = path.suffix == DEB822_SUFFIX
        synced, added = (sources_file if deb822 else list_file)(text, targets, claims)
        if added:
            plan.changes[path.relative_to(root)] = synced
            (plan.stanzas if deb822 else plan.entries).extend(added)
    if plan.changes and _read(root / APT_DROP_IN) != APT_DROP_IN_TEXT:
        plan.changes[APT_DROP_IN] = APT_DROP_IN_TEXT
    return plan


def _listed(output: str) -> list[str]:
    return [
        line.strip().rstrip("/") + "/" for line in output.splitlines() if line.strip()
    ]


def _check_pacman(live: Path, text: str, folder: str, run: Runner) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        candidate = Path(scratch, PACMAN_CONF.name)
        candidate.write_bytes(_encode(text))
        before = run(["pacman-conf", "--config", str(live), "CacheDir"])
        after = run(["pacman-conf", "--config", str(candidate), "CacheDir"])
    listed = _listed(after.stdout)
    first = _listed(before.stdout)[:1]
    if after.returncode != 0 or folder not in listed or listed[:1] != first:
        raise HostSyncError(
            f"pacman-conf does not read the synced pacman.conf as planned: {_tail(after) or listed}"
        )


def _check_apt(plan: Plan, run: Runner) -> None:
    with tempfile.TemporaryDirectory() as scratch:
        listing = Path(scratch, SOURCES_LIST.name)
        listing.write_bytes(_encode("".join(plan.entries)))
        parts = Path(scratch, SOURCE_PARTS.name)
        parts.mkdir()
        if plan.stanzas:
            sources = Path(parts, f"{STATE}{DEB822_SUFFIX}")
            sources.write_bytes(_encode("".join(plan.stanzas)))
        result = run(
            [
                "apt-get",
                "update",
                "-o",
                f"Dir::Etc::SourceList={listing}",
                "-o",
                f"Dir::Etc::SourceParts={parts}",
                "-o",
                "APT::Get::List-Cleanup=0",
                "-o",
                APT_UPDATE_STRICT,
            ]
        )
    if result.returncode != 0:
        raise HostSyncError(
            f"apt-get update fails on the entries pointing at the cache: {_tail(result)}"
        )


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stat = path.stat() if path.exists() else None
    handle, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    scratch = Path(name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        scratch.chmod(stat.st_mode & 0o7777 if stat else 0o644)
        if stat:
            os.chown(scratch, stat.st_uid, stat.st_gid)
        scratch.replace(path)
    except BaseException:
        scratch.unlink(missing_ok=True)
        raise


def state_dir(root: Path) -> Path:
    """Return where a sync keeps the originals of the files it changed.

    Args:
        root: the filesystem root the host's files live under.

    Returns:
        ``<root><DIR_VAR_LIB>/cache-host-sync``.
    """
    return root / read_group_path("DIR_VAR_LIB").lstrip("/") / STATE


def _record(root: Path, plan: Plan) -> None:
    state = state_dir(root)
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    entries = []
    for index, (relative, text) in enumerate(sorted(plan.changes.items())):
        target = root / relative
        backup = f"{index}.orig" if target.is_file() else None
        if backup:
            _write(state / backup, target.read_bytes())
        entries.append(
            {
                "path": str(relative),
                "original": _digest(target),
                "written": hashlib.sha256(_encode(text)).hexdigest(),
                "backup": backup,
            }
        )
    recorded: dict[str, object] = {"files": entries}
    if plan.copies:
        current = {str(p.relative_to(root)): _digest(p) for p in _apt_files(root)}
        written = {e["path"]: e["written"] for e in entries if e["path"] in current}
        recorded["copies"] = plan.copies
        recorded["sources"] = current | written
    manifest = json.dumps(recorded, indent=2, sort_keys=True) + "\n"
    _write(state / MANIFEST, _encode(manifest))


def _strip(root: Path, recorded: dict, original: set[str]) -> list[str]:
    copies = frozenset(recorded["copies"])
    done = []
    for path in _apt_files(root):
        relative = str(path.relative_to(root))
        if relative in original or recorded["sources"].get(relative) == _digest(path):
            continue
        text = _read(path)
        strip = strip_sources if path.suffix == DEB822_SUFFIX else strip_list
        kept = strip(text, copies)
        if kept != text:
            _write(path, _encode(kept))
            done.append(f"removed the cache copies from {path}")
    return done


def revert(root: Path) -> list[str]:
    """Undo the last sync.

    Args:
        root: the filesystem root the host's files live under.

    Returns:
        One line per restored, left or cleaned file; none where no sync is
        recorded. Every file the sync changed and nothing changed since is
        restored byte for byte. On a Debian or Ubuntu host one changed since
        is left in place, a file removed since the sync stays removed, and
        then every apt source or ``apt modernize-sources`` backup that holds
        neither what the sync left there nor its bytes from before the sync
        loses the entries and URIs naming a repository the sync could point a
        copy at.

    Raises:
        HostSyncError: on an Arch host ``pacman.conf`` changed since the sync,
            in which case nothing is restored, or a restored file differs from
            its original.
    """
    state = state_dir(root)
    manifest = state / MANIFEST
    if not manifest.is_file():
        return []
    recorded = json.loads(manifest.read_text(encoding=ENCODING))
    entries = recorded["files"]
    apt = "copies" in recorded
    pending = [e for e in entries if _digest(root / e["path"]) == e["written"]]
    changed = [
        e
        for e in entries
        if _digest(root / e["path"]) not in (e["written"], e["original"])
    ]
    conflicts = [
        f"{root / e['path']} (original: {state / e['backup'] if e['backup'] else 'absent'})"
        for e in changed
    ]
    if conflicts and not apt:
        raise HostSyncError(
            "changed since the sync, so not restored: " + ", ".join(conflicts)
        )
    for entry in pending:
        target = root / entry["path"]
        if entry["backup"]:
            _write(target, (state / entry["backup"]).read_bytes())
        else:
            target.unlink()
    drifted = [e["path"] for e in pending if _digest(root / e["path"]) != e["original"]]
    if drifted:
        raise HostSyncError(
            "restored files differ from their originals: " + ", ".join(drifted)
        )
    restored = [f"restored {root / entry['path']}" for entry in pending]
    left = [
        f"left {root / e['path']} as it is: changed since the sync" for e in changed
    ]
    original = {
        e["path"] for e in entries if _digest(root / e["path"]) == e["original"]
    }
    stripped = _strip(root, recorded, original) if apt else []
    shutil.rmtree(state)
    return [*restored, *left, *stripped]


def _pacman_plan(root: Path, shared: str, run: Runner) -> Plan:
    if not shared.startswith("/"):
        raise HostSyncError(
            "INFINITO_CACHE_SHARED_HOST_PATH is no absolute path; run make dotenv"
        )
    live = root / PACMAN_CONF
    text = _read(live)
    if text is None:
        raise HostSyncError(f"{live} is missing")
    synced = pacman_conf(text, shared)
    if synced == text:
        return Plan()
    _check_pacman(live, synced, shared_folder(shared), run)
    return Plan(changes={PACMAN_CONF: synced})


def _apt_plan(
    root: Path, nexus: str, ubuntu_mirrors: str, declared: Declarations, run: Runner
) -> Plan:
    if archive_of(nexus) is None:
        raise HostSyncError(
            f"the Nexus URL {nexus!r} names no http(s) host; run make dotenv"
        )
    targets = apt_targets(nexus, ubuntu_mirrors, declared)
    plan = apt_plan(root, targets)
    if plan.changes:
        _check_apt(plan, run)
    plan.copies = sorted(
        {t.url for pockets in targets.values() for t in pockets.values()}
    )
    return plan


def sync(
    root: Path,
    *,
    enabled: bool,
    shared: str,
    nexus: str,
    ubuntu_mirrors: str = "",
    run: Runner = _run,
    declared: Declarations | None = None,
) -> list[str]:
    """Make the host's package manager share the cache stack's caches, or restore it.

    Args:
        root: the filesystem root the host's files live under.
        enabled: ``INFINITO_CACHE_HOST_SYNC``.
        shared: ``INFINITO_CACHE_SHARED_HOST_PATH``.
        nexus: base URL the host reaches the package cache's Nexus at.
        ubuntu_mirrors: ``INFINITO_APT_UBUNTU_MIRRORS``.
        run: runs one command and returns the completed process.
        declared: the ``cache:`` declarations; read from the roles when None.

    Returns:
        One line per file restored, cleaned or written.

    Raises:
        HostSyncError: the host is neither Arch, Debian nor Ubuntu, an input
            is missing, the package manager rejects the planned files, or
            ``pacman.conf`` changed since the last sync.
    """
    done = revert(root)
    if not enabled:
        return done
    os_id = host_id(root / OS_RELEASE)
    if os_id == ARCH_HOST_ID:
        plan = _pacman_plan(root, shared, run)
    elif os_id in APT_HOST_IDS:
        plan = _apt_plan(root, nexus, ubuntu_mirrors, declared or declarations(), run)
    else:
        raise HostSyncError(
            f"host ID {os_id or '<none>'} is neither arch, debian nor ubuntu, so no "
            "cache serves its packages; set INFINITO_CACHE_HOST_SYNC=false"
        )
    if not plan.changes:
        return [*done, "no host source is one the cache serves; nothing written"]
    _record(root, plan)
    for relative, text in sorted(plan.changes.items()):
        _write(root / relative, _encode(text))
    return [*done, *(f"wrote {root / relative}" for relative in sorted(plan.changes))]
