"""Catalog checks that need no service, and the scan they share.

The lint suite proves a catalog is structurally sound: in sync with its
sources, placeholders intact, every language present. None of that notices a
translation that is structurally perfect and says the wrong thing, and some of
that is decidable from the catalogs alone. Those checks live here; the ones
whose verdict needs a model live in ``tests/oracle``.

The scan lives in this package rather than beside the checks because every
Python file under ``tests/`` must be named ``test_*``, which would make a
helper module collectable.

Parsing the corpus costs seconds of pure-Python babel work, so the scan trades
memory for time wherever the memory is actually there:

* A catalog whose bytes have not changed since the last run is answered from
  :data:`CACHE_FILE`, which holds the derived offences rather than the
  catalog, and is therefore small enough to keep between runs.
  :data:`RULES_VERSION` is part of every key and is bumped whenever a rule
  below changes, so a stale entry cannot mask an offence.
* The rest are parsed in parallel. The worker count follows the free memory
  and the CPU count, so a loaded or small machine degrades to a serial scan
  instead of swapping. :data:`BYTES_PER_WORKER` is sized for one parsed
  catalog plus babel's intermediates; the largest in the corpus is ~20 MB of
  text and parses to several times that, measured against ``docs/zh``.

Both fall back to the slow-but-correct path on any error: a cache that cannot
be read is ignored, and a pool that cannot start is replaced by a plain loop.
"""

from __future__ import annotations

import json
import os
import time
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from tests.utils.services import progress as _progress
from utils.i18n.catalog import MACHINE_TRANSLATION, catalog_path, read_catalog
from utils.i18n.damage import COLLAPSE_FLOOR as MIN_SOURCE_CHARS
from utils.i18n.damage import MAX_SHARING_SOURCES as MAX_SHARING_SOURCES
from utils.i18n.languages import DOMAINS, load_languages, translatable
from utils.i18n.spans import prose
from utils.i18n.untranslatable import untranslatable

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SUITE = "catalog-scan"
CACHE_FILE = PROJECT_ROOT / "build" / "catalog-scan-cache.json"
RULES_VERSION = 5
EXAMPLES_PER_TRANSLATION = 3
MEMINFO = Path("/proc/meminfo")
BYTES_PER_WORKER = 512 * 1024**2
MEMORY_HEADROOM = 0.5


def progress(message: str) -> None:
    """Append one status line to this suite's log."""
    _progress(SUITE, message)


@dataclass
class Findings:
    """What one pass over every catalog produced."""

    echoes: list[str] = field(default_factory=list)
    collapses: list[str] = field(default_factory=list)
    parsed: int = 0
    reused: int = 0
    workers: int = 1


def available_bytes() -> int:
    """Return the memory the kernel says is available, 0 when unknown.

    ``MemAvailable`` is the kernel's own estimate of what a new workload can
    take without swapping, which is what this decision needs; ``MemFree``
    would ignore reclaimable page cache and understate it badly.
    """
    try:
        raw = MEMINFO.read_text(  # nocheck: cache-read - /proc is synthesised per read and the whole point is the current value
            encoding="utf-8"
        )
        for line in raw.splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 0
    return 0


def worker_count(tasks: int) -> int:
    """Return how many catalogs to parse at once.

    Args:
        tasks: how many catalogs still need parsing.

    Returns:
        At least 1, never more than the tasks, the CPUs, or the workers the
        free memory affords at :data:`MEMORY_HEADROOM` of what is available.
    """
    if tasks <= 1:
        return 1
    cpus = os.cpu_count() or 1
    affordable = int(available_bytes() * MEMORY_HEADROOM // BYTES_PER_WORKER)
    return max(1, min(tasks, cpus, affordable or 1))


def scan_one(path_and_label: tuple[str, str]) -> tuple[list[str], list[str]]:
    """Return one catalog's echo and collapse offences.

    Takes and returns plain types so it can run in a worker process.

    The echo rule is read on ``core`` only. ``docs`` is generated from the
    documentation sources and carries link lists, option tables and data dumps
    whose words are role names; the engine returns those unchanged because
    that is correct, and no length or span rule separates them from a genuine
    echo. Collapse stays on both, where a generated source is as telling as a
    curated one.

    Args:
        path_and_label: the ``.po`` path and its ``<domain>/<code>`` label.
    """
    raw, label = path_and_label
    echoes: list[str] = []
    sources_of: dict[str, list[str]] = defaultdict(list)
    reads_echoes = label.startswith("core/")

    for message in read_catalog(Path(raw)):
        if not message.id or not message.string:
            continue
        if MACHINE_TRANSLATION not in (message.user_comments or []):
            continue
        source, translation = str(message.id), str(message.string)
        if len(prose(source).strip()) < MIN_SOURCE_CHARS:
            continue
        if reads_echoes and source == translation and not untranslatable(source):
            echoes.append(f"{label}: {message.context or '-'} -> {source[:60]!r}")
        seen = sources_of[translation]
        if len(seen) <= EXAMPLES_PER_TRANSLATION:
            seen.append(source)

    collapses = [
        f"{label}: {len(sources)}+ sources share {translation[:60]!r}"
        for translation, sources in sources_of.items()
        if len(sources) > MAX_SHARING_SOURCES
    ]
    return echoes, collapses


def _stamp(path: Path) -> str:
    """Return the identity of a file's content for the cache key."""
    stat = path.stat()
    return f"{RULES_VERSION}:{stat.st_mtime_ns}:{stat.st_size}"


def _load_cache() -> dict[str, list]:
    try:
        return json.loads(
            CACHE_FILE.read_text(  # nocheck: cache-read - the suite rewrites this file at the end of every run, so a cached reader would serve the previous run's copy
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        return {}


def _save_cache(cache: dict[str, list]) -> None:
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache), encoding="utf-8")
    except OSError:
        pass


def _parse(pending: list[tuple[str, str]], findings: Findings) -> list:
    """Parse every pending catalog, in parallel when the memory affords it."""
    findings.workers = worker_count(len(pending))
    progress(
        f"parsing {len(pending)} catalogs on {findings.workers} worker(s), "
        f"{available_bytes() // 1024**2} MB available"
    )
    if findings.workers == 1:
        return [scan_one(task) for task in pending]
    try:
        with ProcessPoolExecutor(max_workers=findings.workers) as pool:
            return list(pool.map(scan_one, pending))
    except OSError:
        progress("pool unavailable, falling back to a serial scan")
        findings.workers = 1
        return [scan_one(task) for task in pending]


def scan() -> Findings:
    """Read every translated catalog and return what the checks need."""
    started = time.perf_counter()
    findings = Findings()
    languages = load_languages(PROJECT_ROOT)
    cache = _load_cache()
    fresh: dict[str, list] = {}
    pending: list[tuple[str, str]] = []

    for domain in DOMAINS:
        for code in translatable(languages, domain):
            path = catalog_path(PROJECT_ROOT, code, domain)
            if not path.is_file():
                continue
            label = f"{domain}/{code}"
            key = f"{label}@{_stamp(path)}"
            cached = cache.get(key)
            if cached is None:
                pending.append((str(path), label))
            else:
                fresh[key] = cached
                findings.echoes += cached[0]
                findings.collapses += cached[1]
                findings.reused += 1

    progress(f"{findings.reused} catalog(s) unchanged since the last run")
    if pending:
        for (path_str, label), (echoes, collapses) in zip(
            pending, _parse(pending, findings), strict=True
        ):
            findings.echoes += echoes
            findings.collapses += collapses
            findings.parsed += 1
            fresh[f"{label}@{_stamp(Path(path_str))}"] = [echoes, collapses]

    _save_cache(fresh)
    progress(
        f"done in {time.perf_counter() - started:.1f}s: {findings.parsed} parsed, "
        f"{findings.reused} reused, {len(findings.echoes)} echo(es), "
        f"{len(findings.collapses)} collapse(s)"
    )
    return findings
