#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

FIELDS = frozenset({"applications", "started", "until"})
DIRECTORY_MODE = 0o755
DOCUMENT_MODE = 0o644
_STAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$")


def stamp(moment: datetime) -> str:
    """
    Args:
        moment: a timezone-aware point in time.

    Returns:
        The moment in UTC as RFC 3339 with a numeric offset.
    """
    if moment.tzinfo is None:
        raise ValueError("a maintenance time must carry a timezone")
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse(value: object) -> datetime:
    """
    Args:
        value: one time field of a maintenance document.

    Returns:
        The aware datetime the field states.
    """
    if not isinstance(value, str) or not _STAMP.match(value):
        raise ValueError(f"{value!r} is not RFC 3339 with a numeric offset")
    return datetime.fromisoformat(value)


def validate(document: object) -> dict:
    """
    Args:
        document: a decoded maintenance document.

    Returns:
        The document, unchanged, once it holds exactly the three fields.
    """
    if not isinstance(document, dict):
        raise TypeError("a maintenance document is a JSON object")
    if set(document) != FIELDS:
        raise ValueError(
            f"a maintenance document holds exactly {sorted(FIELDS)}, "
            f"got {sorted(document)}"
        )
    applications = document["applications"]
    if not isinstance(applications, list) or not all(
        isinstance(application, str) and application for application in applications
    ):
        raise ValueError("applications is a list of application ids")
    if parse(document["until"]) < parse(document["started"]):
        raise ValueError("until lies before started")
    return document


def build(applications: list[str], started: datetime, seconds: int) -> dict:
    """
    Args:
        applications: ids of the applications the run stops.
        started: the start of the run.
        seconds: how long the run may hold them, SYS_TIMEOUT_BACKUP_SERVICES.

    Returns:
        The validated maintenance document.
    """
    if seconds < 0:
        raise ValueError("the maintenance window cannot be negative")
    return validate(
        {
            "applications": sorted(set(applications)),
            "started": stamp(started),
            "until": stamp(started + timedelta(seconds=seconds)),
        }
    )


def write(path: Path, document: dict) -> None:
    """
    Args:
        path: the maintenance document to replace.
        document: the content, validated before it lands.
    """
    validate(document)
    path.parent.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    handle, staged = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(document, stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        Path(staged).chmod(DOCUMENT_MODE)
        Path(staged).replace(path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def read(path: Path) -> dict | None:
    """
    Args:
        path: the maintenance document.

    Returns:
        The validated document, None when it does not exist.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    return validate(json.loads(text))


def announce(path: Path, applications: list[str], seconds: int, now: datetime) -> dict:
    """
    Args:
        path: the maintenance document.
        applications: ids of the applications the run is about to stop.
        seconds: the run's time budget.
        now: the start of the run.

    Returns:
        The document written.
    """
    document = build(applications, now, seconds)
    write(path, document)
    return document


def clear(path: Path, now: datetime) -> dict:
    """
    Args:
        path: the maintenance document.
        now: the moment the run ended.

    Returns:
        The document written: no application, the announced window kept when
        the previous document is readable, otherwise a window closed at now.
    """
    try:
        previous = read(path)
    except (OSError, TypeError, ValueError):
        previous = None
    if previous is None:
        document = build([], now, 0)
    else:
        document = validate(
            {
                "applications": [],
                "started": previous["started"],
                "until": previous["until"],
            }
        )
    write(path, document)
    return document


def active(path: Path, now: datetime) -> list[str]:
    """
    Args:
        path: the maintenance document.
        now: the moment the reader asks for.

    Returns:
        The applications under maintenance at now; empty for a missing
        document, an empty list and a document past its until.
    """
    document = read(path)
    if document is None or parse(document["until"]) < now:
        return []
    return list(document["applications"])


def main(argv: list[str] | None = None) -> int:
    """
    Args:
        argv: the command line without the program name.

    Returns:
        The exit status.
    """
    parser = argparse.ArgumentParser(prog="baudolo-maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    announcing = commands.add_parser("announce")
    announcing.add_argument("--file", type=Path, required=True)
    announcing.add_argument("--seconds", type=int, required=True)
    announcing.add_argument("--application", action="append", default=[])
    clearing = commands.add_parser("clear")
    clearing.add_argument("--file", type=Path, required=True)
    reading = commands.add_parser("active")
    reading.add_argument("--file", type=Path, required=True)
    args = parser.parse_args(argv)
    now = datetime.now(UTC)
    if args.command == "announce":
        announce(args.file, args.application, args.seconds, now)
    elif args.command == "clear":
        clear(args.file, now)
    else:
        print(json.dumps(active(args.file, now)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
