from __future__ import annotations

import base64
import contextlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from utils.cache.files import read_text

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

SIDECAR_SUFFIXES = (".body", ".sig")
PLAYWRIGHT_METADATA = ".links"


@dataclass(frozen=True)
class Unit:
    paths: tuple[Path, ...]
    size: int
    used_at: float


def allocated(st: os.stat_result) -> int:
    return st.st_blocks * 512


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
            size=sum(allocated(files[member]) for member in members),
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
    size = allocated(info) + sum(allocated(member) for member in members)
    size += sum(allocated(os.lstat(directory)) for directory in _directories(root))
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
                    size=allocated(info),
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
                            size=allocated(info),
                            used_at=_used_at(info, fallback),
                        )
                    )
    return units
