"""Strip databases.csv rows for purged application entities."""

from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

from utils.roles.entity_name import get_entity_name

DEFAULT_CSV = Path("/var/lib/infinito/secrets/databases.csv")

_CSV_DELIMITER = ";"
_HEADER_COLUMNS = ("instance", "database", "username", "password")


def _resolve_csv_file() -> Path:
    env_path = os.environ.get("FILE_DATABASE_SECRETS")
    return Path(env_path) if env_path else DEFAULT_CSV


def _row_matches(row: list[str], targets: set[str]) -> bool:
    if len(row) < 3:
        return False
    database = row[1].strip()
    username = row[2].strip()
    return database in targets or username in targets


def _is_header(row: list[str]) -> bool:
    if len(row) < len(_HEADER_COLUMNS):
        return False
    return all(
        row[i].strip().lower() == _HEADER_COLUMNS[i]
        for i in range(len(_HEADER_COLUMNS))
    )


def wipe_database_entries(
    app_ids: list[str], csv_file: Path | None = None
) -> list[str]:
    """Remove rows whose database or username column matches an entity
    derived from *app_ids* via :func:`get_entity_name`."""
    path = csv_file or _resolve_csv_file()
    if not path.exists():
        return []

    targets: set[str] = set()
    for app_id in app_ids:
        entity = get_entity_name(app_id)
        if entity:
            targets.add(entity)
    if not targets:
        return []

    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh, delimiter=_CSV_DELIMITER))

    kept: list[list[str]] = []
    removed: list[str] = []
    for row in rows:
        if not row:
            kept.append(row)
            continue
        if _is_header(row):
            kept.append(row)
            continue
        if _row_matches(row, targets):
            removed.append(f"{row[1].strip()}:{row[2].strip()}")
            continue
        kept.append(row)

    if removed:
        with path.open("w", newline="", encoding="utf-8") as fh:
            csv.writer(fh, delimiter=_CSV_DELIMITER).writerows(kept)

    return removed


def main(argv: list[str]) -> int:
    if not argv:
        print(
            "usage: python -m utils.cleanup.databases_csv <APP_ID> [APP_ID ...]",
            file=sys.stderr,
        )
        return 2

    removed = wipe_database_entries(argv)
    if removed:
        print(f">>> Wiped databases.csv entries: {', '.join(removed)}")
    else:
        print(">>> No databases.csv entries to wipe")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
