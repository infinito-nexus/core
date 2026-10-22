#!/usr/bin/env python3
"""Locate, back up and retire the PostgreSQL clusters inside the data volume.

Every subcommand prints one JSON object on stdout and exits 1 with a message
on stderr when the volume is in a state no deploy may continue from.

Args:
    detect  --root DIR --target MAJOR: the cluster the deploy starts from and
            the major steps up to MAJOR.
    reflink --root DIR --source REL: whether the filesystem below DIR clones
            files next to DIR.
    backup  --root DIR --major MAJOR: a reflink copy of DIR next to it.
    cleanup --root DIR --target MAJOR: removes the clusters pg_upgrade --link
            retired, once the MAJOR cluster exists.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

PG_CONTROL = Path("global") / "pg_control"
PG_CONTROL_RETIRED = Path("global") / "pg_control.old"
NESTED_DIRS = ("data", "pgdata")
ROOT_FOREIGN = (*NESTED_DIRS, "lost+found")


class VolumeError(Exception):
    pass


def target_dir(target: int) -> str:
    """Return the PGDATA of the official image for a major.

    Args:
        target: PostgreSQL major.

    Returns:
        The directory relative to the volume root.
    """
    return f"{target}/docker"


def candidate_dirs(root: Path) -> list[str]:
    """List the directories a cluster may live in, relative to the volume root.

    Args:
        root: The volume root.

    Returns:
        The volume root itself as "", the legacy PGDATA directories, and
        every <major>/docker directory.
    """
    majors = sorted(
        (
            entry.name
            for entry in root.iterdir()
            if entry.is_dir() and entry.name.isdigit()
        ),
        key=int,
    )
    return ["", *NESTED_DIRS, *(target_dir(int(major)) for major in majors)]


def scan(root: Path) -> list[dict]:
    """Find every cluster in the volume.

    Args:
        root: The volume root.

    Returns:
        One dict per cluster with its directory, major, state and the mtime of
        its control file. State "valid" holds global/pg_control, state
        "retired" holds the global/pg_control.old pg_upgrade --link leaves.
    """
    clusters = []
    for rel in candidate_dirs(root):
        path = root / rel
        version_file = path / "PG_VERSION"
        if not version_file.is_file():
            continue
        if (path / PG_CONTROL).is_file():
            state, control = "valid", path / PG_CONTROL
        elif (path / PG_CONTROL_RETIRED).is_file():
            state, control = "retired", path / PG_CONTROL_RETIRED
        else:
            continue
        version = version_file.read_text(encoding="utf-8").strip()
        if not version.isdigit():
            raise VolumeError(
                f"{path} holds PostgreSQL {version}, which has no major-by-major upgrade path"
            )
        clusters.append(
            {
                "dir": rel,
                "major": int(version),
                "state": state,
                "mtime": control.stat().st_mtime,
            }
        )
    return clusters


def detect(root: Path, target: int) -> dict:
    """Decide what the deploy has to do with the clusters in the volume.

    Args:
        root: The volume root.
        target: The pinned PostgreSQL major.

    Returns:
        A plan with "state" "fresh", "current" or "upgrade". "upgrade" names
        the source directory, its major and the steps to the target major.
        "leftovers" lists retired clusters a finished upgrade left behind,
        "ignored" lists older clusters the deploy does not touch.

    Raises:
        VolumeError: The volume holds a newer major, a target cluster outside
            the image's PGDATA, or an upgrade that stopped after linking.
    """
    clusters = scan(root)
    valid = [c for c in clusters if c["state"] == "valid"]
    retired = [c for c in clusters if c["state"] == "retired"]
    pgdata = target_dir(target)

    for cluster in valid:
        if cluster["major"] > target:
            raise VolumeError(
                f"{root / cluster['dir']} was written by PostgreSQL {cluster['major']}, "
                f"newer than the pinned {target}; pin {cluster['major']} or newer"
            )
        if cluster["major"] == target and cluster["dir"] != pgdata:
            raise VolumeError(
                f"{root / cluster['dir']} holds a PostgreSQL {target} cluster outside "
                f"the image's PGDATA {root / pgdata}; move it there"
            )

    for cluster in retired:
        if not any(v["major"] > cluster["major"] for v in valid):
            raise VolumeError(
                f"the upgrade of {root / cluster['dir']} (PostgreSQL {cluster['major']}) "
                "stopped after pg_upgrade --link started, so that cluster cannot start "
                "again; restore the volume from the backup taken before the upgrade"
            )

    leftovers = [c["dir"] for c in retired]
    older = [c for c in valid if c["major"] < target]
    plan = {"target": pgdata, "leftovers": leftovers}

    if any(c["dir"] == pgdata for c in valid):
        return {**plan, "state": "current", "ignored": [c["dir"] for c in older]}
    if not older:
        return {**plan, "state": "fresh", "ignored": []}

    source = max(older, key=lambda c: c["mtime"])
    return {
        **plan,
        "state": "upgrade",
        "source": source["dir"],
        "source_path": str(root / source["dir"]),
        "major": source["major"],
        "majors": list(range(source["major"], target + 1)),
        "ignored": [c["dir"] for c in older if c is not source],
    }


def reflink_supported(root: Path, source: str) -> dict:
    """Probe whether a file of the volume clones next to the volume root.

    Args:
        root: The volume root.
        source: Directory of the cluster whose PG_VERSION is cloned.

    Returns:
        "supported" and, when it is not, the "reason" cp gave.
    """
    probe = root.parent / f".{root.name}.reflink-probe"
    result = subprocess.run(
        ["cp", "--reflink=always", str(root / source / "PG_VERSION"), str(probe)],
        capture_output=True,
        text=True,
        check=False,
    )
    probe.unlink(missing_ok=True)
    if result.returncode == 0:
        return {"supported": True}
    return {"supported": False, "reason": result.stderr.strip()}


def backup(root: Path, major: int, now: datetime) -> dict:
    """Clone the whole volume next to it with reflinks.

    Args:
        root: The volume root.
        major: Major of the cluster about to be upgraded.
        now: Timestamp that names the copy.

    Returns:
        "path" of the copy.

    Raises:
        VolumeError: cp could not clone the volume.
    """
    dest = root.parent / f"{root.name}.pg{major}-{now.strftime('%Y%m%dT%H%M%SZ')}"
    if dest.exists():
        raise VolumeError(f"{dest} exists already")
    result = subprocess.run(
        ["cp", "-a", "--reflink=always", str(root), str(dest)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise VolumeError(f"reflink copy to {dest} failed: {result.stderr.strip()}")
    return {"path": str(dest)}


def remove_cluster(root: Path, rel: str) -> None:
    """Delete one retired cluster.

    Args:
        root: The volume root.
        rel: Directory of the cluster. A <major>/docker cluster takes its
            major directory with it; a cluster in the volume root keeps the
            directories that belong to other clusters.
    """
    if rel == "":
        for entry in root.iterdir():
            if entry.name in ROOT_FOREIGN or entry.name.isdigit():
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry)
            else:
                entry.unlink()
        return
    head = rel.split("/", 1)[0]
    shutil.rmtree(root / (head if head.isdigit() else rel))


def cleanup(root: Path, target: int) -> dict:
    """Remove the clusters pg_upgrade --link retired once the target exists.

    Args:
        root: The volume root.
        target: The pinned PostgreSQL major.

    Returns:
        "removed" directories.

    Raises:
        VolumeError: The target cluster is missing.
    """
    plan = detect(root, target)
    if plan["state"] != "current":
        raise VolumeError(
            f"refusing to remove retired clusters while {root / plan['target']} is not the active cluster"
        )
    for rel in plan["leftovers"]:
        remove_cluster(root, rel)
    return {"removed": plan["leftovers"]}


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse the command line.

    Args:
        argv: Arguments without the program name.

    Returns:
        The parsed namespace.
    """
    parser = argparse.ArgumentParser(prog="cluster.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("detect", "cleanup"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--root", required=True, type=Path)
        cmd.add_argument("--target", required=True, type=int)
    cmd = sub.add_parser("reflink")
    cmd.add_argument("--root", required=True, type=Path)
    cmd.add_argument("--source", required=True)
    cmd = sub.add_parser("backup")
    cmd.add_argument("--root", required=True, type=Path)
    cmd.add_argument("--major", required=True, type=int)
    return parser.parse_args(argv)


def main(argv: list[str]) -> int:
    """Run one subcommand.

    Args:
        argv: Arguments without the program name.

    Returns:
        The exit code.
    """
    args = parse_args(argv)
    root = args.root.resolve(strict=True)
    try:
        if args.command == "detect":
            result = detect(root, args.target)
        elif args.command == "reflink":
            result = reflink_supported(root, args.source)
        elif args.command == "backup":
            result = backup(root, args.major, datetime.now(UTC))
        else:
            result = cleanup(root, args.target)
    except VolumeError as exc:
        print(f"[svc-db-postgres] {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"root": str(root), **result}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
