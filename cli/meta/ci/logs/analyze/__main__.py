from __future__ import annotations

import argparse
import collections
import re
import sys
from pathlib import Path

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_FATAL_TOKENS = ("fatal:", "FAILED!", "Error mounting")
_MSG_KEYS = (
    "Protocol not supported",
    "Error mounting",
    "msg:",
    "not supported",
    "refused",
    "No such",
    "Conflict",
    "timed out",
    "Timeout",
    "unreachable",
    "Cannot",
    "non-zero",
)
_NORMALISE = re.compile(
    r"web-app-[a-z0-9-]+|svc-[a-z0-9-]+|'[^']*'|[0-9a-f]{8,}|192\.168\.[0-9.]+|\b\d+\b"
)


def _app_of(path: Path) -> str:
    name = path.stem.split("__", 1)[-1]
    return re.split(r"Swarm-|Compose-", name)[-1] or name


def _extract(path: Path) -> tuple[str, str]:
    """Return (task, message) for the last real fatal in a job log.

    The real fatal is the last ``fatal:`` / ``FAILED!`` line before the play
    recap; the task is the nearest ``TASK [...]`` above it.
    """
    raw = path.read_text(errors="replace")  # nocheck: cache-read
    lines = [_ANSI.sub("", line).rstrip() for line in raw.splitlines()]
    fatal_idx = None
    for i, line in enumerate(lines):
        if any(token in line for token in _FATAL_TOKENS):
            fatal_idx = i
    if fatal_idx is None:
        return "(no ansible fatal)", ""
    task = "(unknown task)"
    for j in range(fatal_idx, max(fatal_idx - 80, -1), -1):
        if "TASK [" in lines[j]:
            task = lines[j].split("TASK [")[1].split("]")[0]
            break
    message = ""
    for j in range(fatal_idx, min(fatal_idx + 30, len(lines))):
        if any(key in lines[j] for key in _MSG_KEYS):
            raw = lines[j].split("|")[-1].strip()
            message = re.sub(r"^\S*Z\s+", "", raw)
            break
    return task, message


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m cli.meta.ci.logs.analyze",
        description=(
            "Cluster downloaded CI job logs by their root failure. PATH is a logs "
            "directory or a download destination whose logs/ subdirectory is used "
            "when present."
        ),
    )
    p.add_argument("path", help="Logs directory or download destination.")
    p.add_argument(
        "--top", type=int, default=0, help="Show only the N largest clusters."
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    root = Path(args.path)
    logdir = root / "logs" if (root / "logs").is_dir() else root
    files = sorted(logdir.glob("*.log"))
    if not files:
        print(f"[ci-analyze] no .log files under {logdir}", file=sys.stderr)
        return 1

    clusters: dict[str, list[tuple[str, str, str]]] = collections.defaultdict(list)
    for path in files:
        task, message = _extract(path)
        clusters[_NORMALISE.sub("X", task)].append((_app_of(path), task, message))

    ordered = sorted(clusters.values(), key=len, reverse=True)
    if args.top > 0:
        ordered = ordered[: args.top]
    print(f"[ci-analyze] {len(files)} logs, {len(clusters)} clusters")
    for items in ordered:
        apps = ", ".join(app for app, _, _ in items[:16])
        more = " ..." if len(items) > 16 else ""
        print(f"\n[{len(items)}] {items[0][1]}")
        if items[0][2]:
            print(f"     {items[0][2][:140]}")
        print(f"     apps: {apps}{more}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
