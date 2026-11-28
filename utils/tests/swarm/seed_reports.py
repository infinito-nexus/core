"""Run the SBOM engines of the lab scan once per seeded image, into the SBOM seed.

The seed already spares every lab node the Syft export of an image. The engines
that read the SBOM still ran once per node: OSV-Scanner, which takes turns
behind the export slot because it loads whole offline databases into memory,
and the Grype pass over the source-built runtimes. This module runs both once
per seeded image on the runner, while the deploy still runs, with the same
engine images, the same databases the nodes mount and the arguments the node
scan builds, and stores each report beside the SBOM under the fingerprint the
node computes the same way. A node takes a report only when its own fingerprint
is equal (``reuse_seed_report`` of the ``sys-ctl-hlth-runtime`` script) and
scans itself otherwise, so a seeded report can only replace an identical run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from utils.security.engine import RUNTIME_ENGINE, pinned_engine
from utils.security.pipeline import engine_image, pipeline, user_runtime

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

CPUS = "1"
MEMORY_LIMIT = "3g"
OSV = "osv"
RUNTIME_REPORT = "runtime.grype"
PULL_TIMEOUT_S = 600


class Entry(Protocol):
    """One seeded registry image, the ``Entry`` of the seeder.

    Args:
        repository: the repository in the registry.
        digest: the digest of its manifest for the lab architecture.
        layers: its ordered layer digests.
    """

    @property
    def repository(self) -> str: ...

    @property
    def digest(self) -> str: ...

    @property
    def layers(self) -> tuple[str, ...]: ...


def seeded_reports(engine: str) -> tuple[str, ...]:
    """
    Args:
        engine: the engine the deploy pins, empty when none is pinned.

    Returns:
        The SBOM reports a node of that deploy builds per container image:
        OSV-Scanner's when it is the engine, the Grype runtime pass whenever
        Grype is not.
    """
    if not engine:
        return ()
    names = [OSV] if engine == OSV else []
    if engine != RUNTIME_ENGINE:
        names.append(RUNTIME_REPORT)
    return tuple(names)


def node_config():
    """Return the scan configuration a development or CI node runs with.

    Only ``db_update`` enters an engine argument the fingerprint covers, and a
    pinned deploy always reads provided databases.
    """
    return pipeline().scan_config(
        {
            "targets": ["container"],
            "engines": ["syft", OSV],
            "severity": {"CRITICAL": "warn"},
            "fixed_only": True,
            "workers": 1,
            "db_update": False,
            "trivy_unmatched_os": [],
        }
    )


def entry_target(entry: Entry):
    """Return the scan target a node builds for *entry*'s image."""
    return pipeline().Target(
        key=entry.digest.removeprefix("sha256:"),
        kind="container",
        ref=entry.digest,
        label=entry.repository,
        owners=(),
        owner_tags=(),
    )


def report_path(seed: Path, entry: Entry, name: str) -> Path:
    p = pipeline()
    return seed / p.seed_report_file(p.layer_key(entry.layers), name)


def _write(path: Path, document: object) -> None:
    staged = path.with_name(f".{path.name}.tmp")
    staged.write_text(json.dumps(document), encoding="utf-8")
    staged.replace(path)


def seed_reports(
    entries: Iterable[Entry],
    seed: Path,
    root: Path,
    names: Sequence[str],
    images: dict[str, str],
    runner: Callable[[Sequence[str]], subprocess.CompletedProcess],
) -> dict[str, int]:
    """Build the missing seeded reports of every entry whose SBOM is seeded.

    Args:
        entries: the registry images.
        seed: the seed directory.
        root: the host directory of the databases, mounted at the nodes'
            database directory.
        names: the reports to build, see :func:`seeded_reports`.
        images: ``{engine: image}`` of the pinned engine images.
        runner: runs one command.

    Returns:
        ``{report name: how many were stored}``.
    """
    p = pipeline()
    wanted = [
        entry
        for entry in entries
        if all(path.is_file() for path in seed_sbom_paths(seed, entry))
        and not all(report_path(seed, entry, name).is_file() for name in names)
    ]
    stored = dict.fromkeys(names, 0)
    if not wanted:
        return stored
    work = Path(tempfile.mkdtemp(prefix="reports-", dir=seed))
    try:
        layout = p.Layout(
            runtime=(
                *user_runtime(),
                "--cpus",
                CPUS,
                "--memory",
                MEMORY_LIMIT,
                "--memory-swap",
                MEMORY_LIMIT,
            ),
            databases=root,
            sbom=work,
            work=work,
            excludes=(),
        )
        config = node_config()
        ids = {
            engine: p.engine_identity(layout, images[engine], runner)
            for engine in {OSV if name == OSV else RUNTIME_ENGINE for name in names}
        }
        lanes: list[list] = []
        pending: list[tuple[int, Entry, str, str]] = []
        osv_batch: list[tuple[Entry, object, str]] = []
        for entry in wanted:
            target = entry_target(entry)
            syft_path, cyclonedx_path = seed_sbom_paths(seed, entry)
            if OSV in names and not report_path(seed, entry, OSV).is_file():
                rewritten = p.osv_sbom(p._read_json(cyclonedx_path))
                (work / f"{target.key}.osv.cdx.json").write_text(
                    json.dumps(rewritten), encoding="utf-8"
                )
                fingerprint = p.sbom_report_fingerprint(
                    layout,
                    OSV,
                    ids[OSV],
                    p.osv_args(config, ""),
                    p.osv_identity(rewritten),
                )
                if fingerprint is not None:
                    osv_batch.append((entry, target, fingerprint))
            if (
                RUNTIME_REPORT in names
                and not report_path(seed, entry, RUNTIME_REPORT).is_file()
            ):
                reduced = p.runtime_sbom(p._read_json(syft_path))
                if reduced is None:
                    _write(
                        report_path(seed, entry, RUNTIME_REPORT),
                        {"fingerprint": None, "report": None},
                    )
                    continue
                (work / f"{target.key}.runtime.syft.json").write_text(
                    json.dumps(reduced), encoding="utf-8"
                )
                fingerprint = p.sbom_report_fingerprint(
                    layout,
                    RUNTIME_ENGINE,
                    ids[RUNTIME_ENGINE],
                    p.match_args(p.runtime_args(target)),
                    p.syft_identity(reduced),
                )
                if fingerprint is not None:
                    pending.append((len(lanes), entry, target.key, fingerprint))
                    lanes.append(
                        [p.runtime_step(layout, images[RUNTIME_ENGINE], target)]
                    )
        osv_lane = None
        if osv_batch:
            osv_lane = len(lanes)
            lanes.append(
                [
                    p.osv_sbom_step(
                        layout,
                        images[OSV],
                        [target for _entry, target, _fp in osv_batch],
                        config,
                    )
                ]
            )
        results = p.run_lanes(lanes, runner, 1, layout)
        for lane, entry, key, fingerprint in pending:
            report = work / f"{key}.runtime.grype.json"
            if not results[lane] and report.is_file():
                _write(
                    report_path(seed, entry, RUNTIME_REPORT),
                    {"fingerprint": fingerprint, "report": p._read_json(report)},
                )
                stored[RUNTIME_REPORT] += 1
        batched = work / "osv.json"
        if osv_lane is not None and not results[osv_lane] and batched.is_file():
            by_source: dict[str, list] = {}
            for result in p._read_json(batched).get("results") or []:
                by_source.setdefault(result["source"]["path"], []).append(result)
            for entry, target, fingerprint in osv_batch:
                path = f"{p.WORK}/{target.key}.osv.cdx.json"
                _write(
                    report_path(seed, entry, OSV),
                    {
                        "fingerprint": fingerprint,
                        "report": {"results": by_source.get(path, [])},
                    },
                )
                stored[OSV] += 1
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return stored


def seed_sbom_paths(seed: Path, entry: Entry) -> tuple[Path, Path]:
    key = pipeline().layer_key(entry.layers)
    return seed / f"{key}.syft.json", seed / f"{key}.cdx.json"


def pull(images: Iterable[str]) -> bool:
    """Pull the engine images onto the runner, ``False`` when one fails."""
    for image in images:
        try:
            result = subprocess.run(
                ["docker", "pull", "-q", image],
                capture_output=True,
                text=True,
                timeout=PULL_TIMEOUT_S,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode != 0:
            return False
    return True


def engine_images(names: Sequence[str]) -> dict[str, str]:
    """Return ``{engine: pinned image}`` of the engines *names* need."""
    engines = {OSV if name == OSV else RUNTIME_ENGINE for name in names}
    return {engine: engine_image(engine) for engine in sorted(engines)}


def report_names() -> tuple[str, ...]:
    return seeded_reports(pinned_engine())


def prepare() -> tuple[tuple[str, ...], dict[str, str]]:
    """Return the reports this deploy seeds and their engine images.

    Both are empty when the pinned engines cannot be resolved or pulled, so
    the seeder then builds SBOMs only.
    """
    try:
        names = report_names()
        engines = engine_images(names)
    except (OSError, KeyError, ValueError, TypeError) as exc:
        print(
            f"=== swarm-matrix: sbom seed reports unavailable: {exc!r} ===",
            flush=True,
        )
        return (), {}
    if names and not pull(engines.values()):
        print("=== swarm-matrix: sbom seed reports unavailable ===", flush=True)
        return (), {}
    return names, engines


def seed_round(
    entries: Iterable[Entry],
    seed: Path,
    root: Path,
    names: Sequence[str],
    engines: dict[str, str],
) -> None:
    """Build the missing seeded reports once, never raising into the seeder.

    Args:
        entries: the registry images.
        seed: the seed directory.
        root: the host directory of the databases.
        names: the reports to build, see :func:`prepare`.
        engines: their engine images, see :func:`prepare`.
    """
    try:
        stored = seed_reports(
            entries, seed, root, names, engines, pipeline().default_runner
        )
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        print(f"=== swarm-matrix: sbom seed reports failed: {exc!r} ===", flush=True)
        return
    if any(stored.values()):
        print(f"=== swarm-matrix: sbom seed reports built: {stored} ===", flush=True)
