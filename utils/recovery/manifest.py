"""Read the manifest a baudolo generation carries, with nothing but ``json``.

Import-light for the same reason as :mod:`utils.recovery.layout`: this runs on
hosts that have no baudolo.

Generations written before the manifest existed carry none, so :func:`read`
reports absence rather than an empty verdict and callers can fall back.

Exit codes as a module: 0 with one ``<volume>\\t<engine>`` line per undumped
database volume, 2 when the generation carries no manifest, 64 on bad usage.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from utils.recovery import layout as fallback
from utils.recovery.layout import MANIFEST_FILE, MANIFEST_SCHEMA


def read(generation_dir: Path | str) -> dict | None:
    """The manifest document, or None when the generation carries none.

    Args:
        generation_dir: the ``<backups>/<hash>/<repo>/<generation>`` directory.

    Raises:
        ValueError: the manifest is unreadable, or states a schema this code
            does not know. A newer schema must not be guessed at: the fields
            this reader relies on may mean something else in it.
    """
    path = Path(generation_dir) / MANIFEST_FILE
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")  # nocheck: cache-read - written this run
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{path} is unreadable: {error}") from error
    schema = document.get("schema")
    if schema != MANIFEST_SCHEMA:
        raise ValueError(
            f"{path} states schema {schema!r}, this reader knows {MANIFEST_SCHEMA}"
        )
    return document


def layout_of(generation_dir: Path | str) -> dict[str, str]:
    """The names payload is stored under in THIS generation.

    Read from the generation's own manifest, so a tree written by any version
    is walked with the names that version used. Generations older than the
    manifest cannot say, and only for those does the fallback in
    :mod:`utils.recovery.layout` apply.
    """
    document = read(generation_dir)
    if document is not None and document.get("layout"):
        return document["layout"]
    return {
        "files_dir": fallback.FILES_DIR,
        "sql_dir": fallback.SQL_DIR,
        "dump_suffix": fallback.DUMP_SUFFIX,
        "cluster_suffix": fallback.CLUSTER_SUFFIX,
    }


def globs_of(names: dict[str, str]) -> tuple[str, str]:
    """``(files_glob, dump_glob)`` for the layout *names* describe.

    Takes the names rather than the directory so a caller that needs both
    reads the manifest once.
    """
    return (
        f"*/{names['files_dir']}",
        f"*/{names['sql_dir']}/*{names['dump_suffix']}",
    )


def volumes(generation_dir: Path | str) -> dict[str, dict]:
    """Every volume the generation recorded, empty for an old generation."""
    document = read(generation_dir)
    return {} if document is None else document.get("volumes", {})


def undumped(generation_dir: Path | str) -> list[tuple[str, str]]:
    """``(volume, engine)`` for every database volume that carries no dump."""
    return sorted(
        (name, state.get("engine") or "unknown")
        for name, state in volumes(generation_dir).items()
        if state.get("database") and not state.get("dumped")
    )


def engine_by_volume(generation_dir: Path | str) -> dict[str, str]:
    """The engine each database volume was dumped from, as the run detected it."""
    return {
        name: state["engine"]
        for name, state in volumes(generation_dir).items()
        if state.get("engine")
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: python -m utils.recovery.manifest <generation-dir>", file=sys.stderr
        )
        return 64
    if read(args[0]) is None:
        return 2
    for volume, engine in undumped(args[0]):
        print(f"{volume}\t{engine}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
