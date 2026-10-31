"""Download the vulnerability databases into one shared directory.

The CI ``vulnerability-db`` job fills the Actions cache with it, and a local
deploy refreshes the host directory every stack mounts read-only, so no
stack and no node downloads a database itself.
"""

from __future__ import annotations

import fcntl
import shutil
import tempfile
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
LOCK_FILE = Path(tempfile.gettempdir()) / "infinito-vulnerability-db.lock"


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
            fetch(osv_url(zip_file.parent.name), zip_file)
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


def refresh(
    root: Path,
    engines: Sequence[str],
    runner,
    fetch: Callable[[str, Path], None],
) -> list[str]:
    """Download every database of *engines* that is missing or stale.

    The host-wide lock keeps two deploys from writing the shared directory
    at once.

    Returns:
        The error lines of the downloads that failed.
    """
    p = pipeline()
    with LOCK_FILE.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        outdated = [engine for engine in engines if stale(p, root, engine, time.time())]
        return fetch_databases(p, root, outdated, runner, fetch) if outdated else []
