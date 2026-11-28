"""Mirror the hlth-runtime findings of a main run's deploys into GitHub issues."""

from __future__ import annotations

import argparse
import functools
import json
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from cli.contributing.security.issues.__main__ import (
    GH_FAILURES,
    Tracker,
    pinned,
    run_gh,
    sync,
    title,
)
from utils import PROJECT_ROOT
from utils.docker.image.discovery import image_source, iter_role_images
from utils.roles.entity.apps import apps_for_entity
from utils.security.engine import ROLE

if TYPE_CHECKING:
    from collections.abc import Callable, Collection, Iterator, Sequence

MAIN_REF = "refs/heads/main"
ARTIFACTS = "rescue-diagnostics-*"
MIRROR_PREFIX_ENV = "INFINITO_GHCR_MIRROR_PREFIX"
UNMANAGED = "unmanaged container "
FINDING = re.compile(
    r"(?:❌|⚠️?|ℹ️?) (?P<engine>\S+) (?P<kind>container|host) (?P<scope>.+?): "
    r"(?P<id>\S+) (?P<severity>[A-Z]+) (?P<package>.+) (?P<installed>\S+) "
    r"\((?:fixed in (?P<fixed>.+)|no fix)\)"
    r"(?: suppressed until (?P<until>\d{4}-\d{2}-\d{2}))?$"
)
EVENT_MARK = '{"event": "hlth_runtime.'
EVENT = re.compile(r"\{\"event\": \"hlth_runtime\.(?:target|summary)\".*$")
RUNTIME = Tracker(
    label="🔥 vulnerability-runtime",
    color="D93F0B",
    description="hlth-runtime reports a CVE at the threshold on a main deploy",
    source=lambda row: f"Runtime: `{row['runtime']}`",
    artifact="the `rescue-diagnostics-*` artifacts of the main run",
    gone="No main deploy that scanned this target reports a CVE at the threshold any more.",
    covers=lambda report, title: title in report["scanned"],
    live=lambda report: (
        {*report["running"], *pinned(report)} if report["complete"] else None
    ),
)


def host_image(distro: str) -> str:
    """Return the stable image field of the host scan of one distro's deploy node."""
    return f"host {distro}"


def upstream(label: str, prefix: str) -> str:
    """Return the image reference an issue title names for a running image.

    Args:
        label: the image name the container runs,
            ``[registry/]repository[:tag][@digest]``.
        prefix: the GHCR mirror prefix, see ``INFINITO_GHCR_MIRROR_PREFIX``.

    Returns:
        A mirror copy as the upstream pull reference the mirror scan titles
        its issue with, any other image, such as a local build, as it runs.
    """
    name = label.split("@", 1)[0]
    mirrored = re.fullmatch(
        rf"ghcr\.io/[^/]+/[^/]+/{re.escape(prefix)}/(?P<upstream>.+)", name
    )
    if mirrored is None:
        return name
    repository, separator, tag = mirrored["upstream"].rpartition(":")
    if not separator or "/" in tag:
        return mirrored["upstream"]
    return image_source(repository, tag)


@functools.cache
def roles_of(stack: str) -> str | None:
    """Return the roles of a compose project or swarm stack, comma-joined."""
    return ",".join(apps_for_entity(stack, roles_dir=PROJECT_ROOT / "roles")) or None


def row(found: re.Match, distro: str, prefix: str) -> dict[str, Any]:
    """Return one finding line as an issue row."""
    engine = found["engine"]
    if found["kind"] == "host":
        image = runtime = host_image(distro)
        role, service = ROLE, engine
    else:
        scope = found["scope"]
        if scope.startswith(UNMANAGED):
            role, service, label = None, None, scope.removeprefix(UNMANAGED)
        else:
            owner, label = scope.split(" ", 1)
            stack, service = owner.split("/", 1)
            role = roles_of(stack)
        image, runtime = upstream(label, prefix), label.split("@", 1)[0]
    return {
        "engine": engine,
        "role": role,
        "service": service,
        "image": image,
        "runtime": runtime,
        "id": found["id"],
        "severity": found["severity"],
        "package": found["package"],
        "installed": found["installed"],
        "fixed": found["fixed"] or "",
        "suppressed_until": found["until"],
    }


def target_image(event: dict[str, Any], distro: str, prefix: str) -> str:
    """Return the image field of the target one ``hlth_runtime.target`` event names."""
    if event["kind"] == "host":
        return host_image(distro)
    return upstream(event["image"].rsplit("@", 1)[0], prefix)


def journals(artifact: Path) -> Iterator[tuple[str, Path]]:
    """Yield ``(distro, journal)`` for every journal one artifact holds."""
    for path in sorted(artifact.rglob("*journal.txt")):
        parts = path.relative_to(artifact).parts
        if len(parts) > 1 and (
            path.name == "journal.txt" or path.name.endswith(".journal.txt")
        ):
            yield parts[0], path


def read_journal(
    path: Path, distro: str, prefix: str
) -> tuple[list[dict[str, Any]], set[str], int, bool]:
    """Read the hlth-runtime lines of one journal.

    Returns:
        ``(rows, titles, errors, summarized)``: one row per finding line,
        the issue title of every target an event names, the engine errors
        the summary events count plus every event line that does not parse
        plus one for target events no summary event follows, and whether
        the journal holds a summary event.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    failed = 0
    summarized = False
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            text = line.rstrip("\n")
            if "(fixed in " in text or "(no fix)" in text:
                found = FINDING.search(text)
                if found is not None:
                    rows.append(row(found, distro, prefix))
                    continue
            event = EVENT.search(text) if EVENT_MARK in text else None
            if event is None:
                continue
            try:
                data = json.loads(event.group(0))
            except json.JSONDecodeError:
                failed += 1
                continue
            if data["event"] == "hlth_runtime.summary":
                failed += data["errors"]
                summarized = True
            else:
                seen.add(title({"image": target_image(data, distro, prefix)}))
    if seen and not summarized:
        failed += 1
    return rows, seen, failed, summarized


def collect(root: Path, prefix: str) -> dict[str, Any]:
    """Read every rescue artifact below *root* into one issue report.

    Args:
        root: holds one directory per downloaded artifact.
        prefix: the GHCR mirror prefix.

    Returns:
        ``findings``: one row per distinct finding; ``errors``: one line per
        journal whose check runs reported engine errors, an unreadable
        event or targets without a summary, and one per artifact without a
        summary; ``scanned``: the issue titles of every target a journal
        without such an error scanned, the only issues an absent finding
        may close; ``running``: the issue titles of every target any
        journal names, with or without such an error; ``complete``:
        whether every artifact holds a journal with a summary and no
        journal naming targets without one, so no deploy of the run
        stopped before its scan.
    """
    rows: dict[tuple, dict[str, Any]] = {}
    scanned: set[str] = set()
    blocked: set[str] = set()
    errors: list[str] = []
    unscanned: list[str] = []
    for artifact in sorted(path for path in root.iterdir() if path.is_dir()):
        summaries = 0
        unfinished = False
        for distro, path in journals(artifact):
            found, seen, failed, summarized = read_journal(path, distro, prefix)
            rows.update((tuple(sorted(item.items())), item) for item in found)
            (blocked if failed else scanned).update(seen)
            summaries += summarized
            unfinished = unfinished or (bool(seen) and not summarized)
            if failed:
                errors.append(f"{path.relative_to(root)}: {failed} engine error(s)")
        if not summaries:
            unscanned.append(f"{artifact.name}: no journal with a hlth-runtime summary")
        elif unfinished:
            unscanned.append(
                f"{artifact.name}: a journal names targets without a hlth-runtime summary"
            )
    return {
        "findings": [rows[key] for key in sorted(rows, key=str)],
        "errors": [*errors, *unscanned],
        "scanned": sorted(scanned - blocked),
        "running": sorted(scanned | blocked),
        "complete": not unscanned,
    }


def report(
    *,
    run_id: str,
    repo: str,
    ref: str,
    dest: Path,
    prefix: str,
    pinned: Collection[str],
    gh: Callable[[Sequence[str]], str],
) -> list[str]:
    """Sync the runtime vulnerability issues of one main run.

    Args:
        run_id: the workflow run whose deploys are reported.
        repo: ``owner/name``.
        ref: the ref the run built; anything but ``refs/heads/main`` files
            nothing.
        dest: where the rescue artifacts are downloaded.
        prefix: the GHCR mirror prefix.
        pinned: the image reference every role pins; the issue of a pinned
            image never closes as superseded, even when this run deployed
            no role that runs it.
        gh: runs ``gh`` with the given arguments and returns its stdout.

    Returns:
        What was done, one line per action; a ``failed`` line when the
        download failed, which then syncs nothing.
    """
    if ref != MAIN_REF:
        return [f"skipped: {ref} is not {MAIN_REF}, no issue is filed"]
    try:
        gh(
            [
                "run",
                "download",
                run_id,
                "--repo",
                repo,
                "--pattern",
                ARTIFACTS,
                "-D",
                str(dest),
            ]
        )
    except GH_FAILURES as exc:
        return [f"failed downloading the {ARTIFACTS} artifacts of {run_id}: {exc}"]
    found = {**collect(dest, prefix), "pinned": sorted(pinned)}
    errors = [f"error {line}" for line in found["errors"]]
    return [*errors, *sync(found, repo, gh, RUNTIME)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Mirror the hlth-runtime findings of a main run into GitHub issues."
    )
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--repo", required=True, help="owner/name")
    parser.add_argument("--ref", required=True, help="The ref the run built")
    parser.add_argument("--dir", required=True, help="Download directory")
    args = parser.parse_args(argv)
    lines = report(
        run_id=args.run_id,
        repo=args.repo,
        ref=args.ref,
        dest=Path(args.dir),
        prefix=os.environ[MIRROR_PREFIX_ENV],
        pinned={ref.source for ref in iter_role_images(PROJECT_ROOT)},
        gh=run_gh,
    )
    for line in lines:
        print(line)
    return 1 if any(line.startswith("failed ") for line in lines) else 0


if __name__ == "__main__":
    sys.exit(main())
