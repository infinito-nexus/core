#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import TYPE_CHECKING, Any

from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.docker.image.discovery import ImageRef, iter_role_images
from utils.docker.mirror import mirror_image
from utils.docker.registry import image_platform_digest
from utils.security.engine import ROLE, SBOM_BUILDER, SCANNERS
from utils.security.pipeline import engine_image, pipeline, role_services, user_runtime
from utils.security.suppressions import role_suppressions

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping, Sequence
    from types import ModuleType

OS_NAME = "linux"
ARCHITECTURE = "amd64"


def mirror_ref(ref: ImageRef) -> str:
    """Return the GHCR mirror repository of a pinned image.

    Raises:
        SystemExit: the mirror namespace cannot be resolved.
    """
    mirrored = mirror_image(f"{ref.registry}/{ref.name}")
    if mirrored is None:
        raise SystemExit(
            "the GHCR mirror is not resolvable: set INFINITO_GHCR_MIRROR_PREFIX "
            "and a GitHub remote or GITHUB_REPOSITORY"
        )
    return mirrored


def resolve_digests(
    refs: Sequence[ImageRef],
    digest_of: Callable[[str, str], str | None],
    workers: int,
) -> tuple[dict[str, list[ImageRef]], dict[str, str], list[str]]:
    """Group the pinned images by the digest their mirror copy serves.

    Args:
        refs: the pinned images.
        digest_of: ``(mirror repository, tag) -> digest``.
        workers: parallel registry requests.

    Returns:
        ``(refs by digest, mirror repository by digest, errors)``.
    """
    mirrors = [mirror_ref(ref) for ref in refs]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        digests = list(
            pool.map(
                lambda pair: digest_of(pair[0], pair[1].version),
                zip(mirrors, refs, strict=True),
            )
        )
    grouped: dict[str, list[ImageRef]] = {}
    sources: dict[str, str] = {}
    errors = []
    for ref, mirror, digest in zip(refs, mirrors, digests, strict=True):
        if digest is None:
            errors.append(
                f"{ref.role}:{ref.service} {mirror}:{ref.version}: the mirror served no digest"
            )
            continue
        grouped.setdefault(digest, []).append(ref)
        sources.setdefault(digest, mirror)
    return grouped, sources, errors


def targets_of(p: ModuleType, grouped: Mapping[str, Sequence[ImageRef]]) -> list:
    """Return one pipeline target per digest, owned by every role service pinning it."""
    return [
        p.Target(
            key=digest.removeprefix("sha256:"),
            kind="container",
            ref=digest,
            label=refs[0].source,
            owners=tuple(sorted({(ref.role, ref.service) for ref in refs})),
            owner_tags=tuple(
                sorted({((ref.role, ref.service), ref.version) for ref in refs})
            ),
        )
        for digest, refs in sorted(grouped.items())
    ]


def sbom_step(p: ModuleType, layout, target, source: str):
    args = [
        "scan",
        f"registry:{source}@{target.ref}",
        "-o",
        f"syft-json={p.SBOM}/{target.key}.syft.json",
        "-o",
        f"cyclonedx-json={p.SBOM}/{target.key}.cdx.json",
        "-q",
    ]
    scratch = p.scratch_of(SBOM_BUILDER, target.key)
    return p.Step(
        f"syft {target.label}",
        p.run_argv(
            layout,
            SBOM_BUILDER,
            engine_image(SBOM_BUILDER),
            args,
            target=None,
            extra_env={},
            scratch=scratch,
        ),
        p.SUCCESS,
        scratch,
        False,
    )


def trivy_step(p: ModuleType, layout, target, os_args: Sequence[str]):
    args = [
        "sbom",
        *p.TRIVY_COMMON,
        "--skip-db-update",
        "--skip-java-db-update",
        "--cache-backend",
        "memory",
        "--scanners",
        "vuln",
        *os_args,
        "--format",
        "json",
        "--output",
        f"{p.WORK}/{target.key}.trivy.json",
        f"{p.SBOM}/{target.key}.cdx.json",
    ]
    scratch = p.scratch_of("trivy", target.key)
    return p.Step(
        f"trivy {target.label}",
        p.run_argv(
            layout,
            "trivy",
            engine_image("trivy"),
            args,
            target=None,
            extra_env={},
            scratch=scratch,
        ),
        p.SUCCESS,
        scratch,
        False,
    )


def grype_step(p: ModuleType, layout, target):
    args = [
        f"sbom:{p.SBOM}/{target.key}.syft.json",
        "-o",
        "json",
        "--file",
        f"{p.WORK}/{target.key}.grype.json",
        "-q",
    ]
    scratch = p.scratch_of("grype", target.key)
    return p.Step(
        f"grype {target.label}",
        p.run_argv(
            layout,
            "grype",
            engine_image("grype"),
            args,
            target=None,
            extra_env={"GRYPE_DB_AUTO_UPDATE": "false"},
            scratch=scratch,
        ),
        p.SUCCESS,
        scratch,
        False,
    )


def scan_tree(
    p: ModuleType,
    targets: Sequence,
    sources: Mapping[str, str],
    config,
    layout,
    runner,
) -> tuple[list, list[str]]:
    """Build the missing SBOMs, then run every scanner over the SBOM tree.

    Returns:
        ``(findings, errors)``.
    """
    images = {engine: engine_image(engine) for engine in SCANNERS}
    databases = p.prepare_databases(config, images, layout, runner)
    errors = p._flat(databases.values())
    scanners = [engine for engine, lines in databases.items() if not lines]

    pending = [
        target
        for target in targets
        if not all(path.is_file() for path in p.sbom_paths(layout, target))
    ]
    results = p.run_lanes(
        [[sbom_step(p, layout, target, sources[target.ref])] for target in pending],
        runner,
        config.workers,
        layout.work,
    )
    errors += p._flat(results)
    failed = {
        target.key for target, lines in zip(pending, results, strict=True) if lines
    }
    ready = [target for target in targets if target.key not in failed]

    lanes = []
    today = dt.datetime.now(tz=dt.UTC).date()
    for target in ready:
        if "trivy" in scanners:
            os_args = p.trivy_os_args(layout, target, scanners, config, today)
            lanes.append([trivy_step(p, layout, target, os_args)])
        if "grype" in scanners:
            lanes.append([grype_step(p, layout, target)])
    if "osv" in scanners and ready:
        for target in ready:
            cdx = p.sbom_paths(layout, target)[1]
            (layout.work / f"{target.key}.osv.cdx.json").write_text(
                json.dumps(p.osv_sbom(json.loads(read_text(str(cdx))))),
                encoding="utf-8",
            )
        lanes.append([p.osv_sbom_step(layout, images["osv"], ready, config)])
    errors += p._flat(p.run_lanes(lanes, runner, config.workers, layout.work))

    findings = []
    for target in ready:
        for engine, parse in (("trivy", p.parse_trivy), ("grype", p.parse_grype)):
            report = layout.work / f"{target.key}.{engine}.json"
            if engine in scanners and report.is_file():
                findings += parse(json.loads(read_text(str(report))), target.key)
    batched = layout.work / "osv.json"
    if batched.is_file():
        by_file = {
            f"{p.WORK}/{target.key}.osv.cdx.json": target.key for target in ready
        }
        findings += p.parse_osv(
            json.loads(read_text(str(batched))), by_file.__getitem__
        )
    return findings, errors


def suppressions_of(p: ModuleType, roles: Sequence[str]):
    """Return the declared suppressions of *roles*, keyed by role and service."""
    return p.Suppressions(
        containers={
            role: {
                service: tuple(
                    p.Suppression(
                        id=entry.id, image_tag=entry.image_tag, until=entry.until
                    )
                    for entry in entries
                )
                for service, entries in role_suppressions(
                    PROJECT_ROOT / "roles", role
                ).items()
            }
            for role in sorted(set(roles))
        },
        host={},
    )


def report_rows(verdicts: Sequence, sources: Mapping[str, str]) -> list[dict[str, Any]]:
    """Return every verdict as a row for the issue tracker.

    A suppressed row carries the suppression's last day in
    ``suppressed_until``; a failing row carries ``None`` there.
    """
    rows = []
    for verdict in verdicts:
        finding = verdict.finding
        role, service = verdict.owner
        rows.append(
            {
                "engine": finding.engine,
                "role": role,
                "service": service,
                "image": verdict.target.label,
                "mirror": sources[verdict.target.ref],
                "digest": verdict.target.ref,
                "id": finding.id,
                "ids": list(finding.ids),
                "severity": finding.severity,
                "package": finding.package,
                "installed": finding.installed,
                "fixed": finding.fixed,
                "suppressed_until": (
                    verdict.rule.until.isoformat() if verdict.suppressed else None
                ),
            }
        )
    return rows


def failing(rows: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Return the rows no suppression covers."""
    return [row for row in rows if row["suppressed_until"] is None]


def scan_config(p: ModuleType, workers: int):
    services = role_services()
    runtime = services["runtime"]
    return p.scan_config(
        {
            "targets": ["container"],
            "engines": [*SCANNERS, SBOM_BUILDER],
            "severity": runtime["severity"],
            "fixed_only": runtime["fixed_only"],
            "workers": workers,
            "db_update": True,
            "trivy_unmatched_os": services["trivy"]["unmatched_os"],
        }
    )


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a Syft SBOM of every pinned role image straight from the GHCR "
            "mirror, cached by digest, and scan the SBOM tree with Trivy, Grype "
            f"and OSV at the threshold and suppressions of {ROLE}."
        )
    )
    parser.add_argument("--cache-dir", required=True, help="SBOM tree and databases")
    parser.add_argument(
        "--report", required=True, help="JSON file the failing findings go to"
    )
    parser.add_argument(
        "--workers", required=True, type=int, help="Parallel engine runs"
    )
    args = parser.parse_args(argv)

    p = pipeline()
    config = scan_config(p, args.workers)
    refs = sorted(
        iter_role_images(PROJECT_ROOT), key=lambda ref: (ref.role, ref.service)
    )
    grouped, sources, errors = resolve_digests(
        refs,
        lambda image, tag: image_platform_digest(
            image, tag, os_name=OS_NAME, architecture=ARCHITECTURE
        ),
        config.workers,
    )
    targets = targets_of(p, grouped)
    cache = Path(args.cache_dir).resolve()
    (cache / "sbom").mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="run-", dir=cache))
    try:
        layout = p.Layout(
            runtime=user_runtime(),
            databases=cache / "db",
            sbom=cache / "sbom",
            work=work,
            excludes=(),
        )
        findings, scan_errors = scan_tree(
            p, targets, sources, config, layout, p.default_runner
        )
        p.prune_sboms(layout, targets)
    finally:
        shutil.rmtree(work)
    errors += scan_errors
    judged = p.verdicts(
        findings,
        {target.key: target for target in targets},
        config,
        suppressions_of(p, [ref.role for ref in refs]),
        dt.datetime.now(tz=dt.UTC).date(),
    )
    rows = report_rows(judged, sources)
    report = Path(args.report)
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(
        json.dumps({"findings": rows, "errors": errors}, indent=2), encoding="utf-8"
    )
    for verdict in judged:
        line = f"{verdict.where()}: {verdict.detail()}"
        print(
            f"ℹ️ {line} suppressed until {verdict.rule.until}"
            if verdict.suppressed
            else f"❌ {line}"
        )
    for error in errors:
        print(f"❌ {error}")
    failures = failing(rows)
    print(
        f"\n{len(refs)} pinned image(s), {len(targets)} digest(s), "
        f"{len(failures)} failing and {len(rows) - len(failures)} suppressed "
        f"finding(s), {len(errors)} error(s)"
    )
    return 1 if failures or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
