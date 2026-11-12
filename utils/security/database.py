"""Download the vulnerability databases into one shared directory."""

from __future__ import annotations

import fcntl
import http.client
import os
import shutil
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from utils.security.pipeline import engine_image, pipeline, role_services, user_runtime

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from types import ModuleType

OSV_BUCKET = "https://osv-vulnerabilities.storage.googleapis.com"
DOWNLOAD_TIMEOUT_SECONDS = 600
MAX_AGE_SECONDS = 24 * 3600
LOCK_NAME = ".lock"


def osv_url(ecosystem: str) -> str:
    return f"{OSV_BUCKET}/{urllib.parse.quote(ecosystem)}/all.zip"


def fetch_url(url: str, destination: Path) -> None:
    request = urllib.request.Request(  # noqa: S310 - https download from the OSV bucket
        url, headers={"User-Agent": "infinito-nexus-vulnerability-db"}
    )
    with (
        urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response,  # noqa: S310 - https download from the OSV bucket
        destination.open("wb") as target,
    ):
        shutil.copyfileobj(response, target)


def osv_zips(p: ModuleType, root: Path) -> list[Path]:
    """Return the OSV offline database file of every listed ecosystem."""
    return [
        root / "osv" / p.OSV_DB_LAYOUT / ecosystem / "all.zip"
        for ecosystem in role_services()["osv"]["ecosystems"]
    ]


def fetch_databases(
    p: ModuleType,
    root: Path,
    engines: Sequence[str],
    runner,
    fetch: Callable[[str, Path], None],
) -> list[str]:
    """Download the databases of *engines* into *root*.

    Args:
        p: the vulnerability pipeline.
        root: the database root, one directory per engine.
        engines: the engines whose database to download.
        runner: runs one engine command.
        fetch: ``(url, destination)`` downloader.

    Returns:
        The error lines of the engines whose download failed.
    """
    layout = p.Layout(
        runtime=user_runtime(), databases=root, sbom=root, work=root, excludes=()
    )
    lanes = []
    for engine in engines:
        (root / engine).mkdir(parents=True, exist_ok=True)
        if engine != "osv":
            lanes.append(p.db_steps(engine, layout, engine_image(engine)))
    errors = p._flat(p.run_lanes(lanes, runner, len(lanes) or 1))
    if "osv" in engines:
        for zip_file in osv_zips(p, root):
            zip_file.parent.mkdir(parents=True, exist_ok=True)
            partial = zip_file.with_name(f"{zip_file.name}.part")
            try:
                fetch(osv_url(zip_file.parent.name), partial)
            except (OSError, http.client.HTTPException) as exc:
                partial.unlink(missing_ok=True)
                errors.append(f"osv {zip_file.parent.name}: {exc}")
                continue
            partial.replace(zip_file)
    for engine in engines:
        errors += p.missing_databases(engine, root)
    return errors


def database_files(p: ModuleType, root: Path, engine: str) -> list[Path]:
    """Return the files that make up one engine's database."""
    if engine == "osv":
        return osv_zips(p, root)
    return [root / engine / marker for marker in p.DB_MARKERS[engine]]


def stale(p: ModuleType, root: Path, engine: str, now: float) -> bool:
    """Whether one engine's database is missing or older than a day."""
    files = database_files(p, root, engine)
    return not all(
        path.is_file() and now - path.stat().st_mtime < MAX_AGE_SECONDS
        for path in files
    )


def hand_over(root: Path, paths: Sequence[Path]) -> None:
    """Give *paths* and everything below them to the owner of *root*.

    Args:
        root: the shared database directory.
        paths: what this process may have written below *root*; a path it
            did not create is skipped.
    """
    if os.geteuid() != 0:
        return
    owner = root.stat()
    for path in (path for path in paths if path.exists()):
        os.chown(path, owner.st_uid, owner.st_gid)
        tree = os.walk(path)  # nocheck: project-walk - not the repository
        for directory, dirs, files in tree:
            for name in (*dirs, *files):
                os.chown(Path(directory) / name, owner.st_uid, owner.st_gid)


def refresh(
    root: Path,
    engines: Sequence[str],
    runner,
    fetch: Callable[[str, Path], None],
) -> list[str]:
    """Download every database of *engines* that is missing or stale.

    Returns:
        The error lines of the downloads that failed.
    """
    p = pipeline()
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / LOCK_NAME
    with lock_path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        outdated = [engine for engine in engines if stale(p, root, engine, time.time())]
        errors = fetch_databases(p, root, outdated, runner, fetch) if outdated else []
        hand_over(root, [lock_path, *(root / engine for engine in outdated)])
        return errors
