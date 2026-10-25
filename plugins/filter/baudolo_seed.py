from __future__ import annotations

import base64
import binascii
import csv
import io
import re

COLUMNS = ("instance", "database", "username", "password")
CLUSTER_ROW = "*"
_NAME_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_-]*$")


def _serialize(rows) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\n")
    writer.writerows(rows)
    return buffer.getvalue()


def _database(value: str) -> str | None:
    text = value.strip()
    if text == CLUSTER_ROW:
        return CLUSTER_ROW
    if not text or text.lower() == "nan" or not _NAME_RE.match(text):
        return None
    return text


def baudolo_seeded(content: str) -> dict:
    """The rows of a ``databases.csv`` and whether ``baudolo-seed`` wrote it.

    Args:
      content: the file as base64, as ``slurp`` returns it; ``""`` for a file
        that is absent or empty.

    Returns:
      dict:
        canonical - True only when the text is byte for byte what
                    ``baudolo-seed`` writes for these rows; undecodable or
                    hand-formatted text is False
        rows      - [instance, database, username, password] lists in file
                    order, empty when not canonical
    """
    try:
        text = base64.b64decode(content, validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return {"canonical": False, "rows": []}
    if not text:
        return {"canonical": True, "rows": []}
    parsed = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    if not parsed or tuple(parsed[0]) != COLUMNS:
        return {"canonical": False, "rows": []}
    rows = parsed[1:]
    canonical = (
        all(len(row) == len(COLUMNS) for row in rows) and _serialize(parsed) == text
    )
    return {"canonical": canonical, "rows": rows if canonical else []}


def baudolo_seed_current(seeded, instance, database, username, password) -> bool:
    """Whether ``baudolo-seed`` with these arguments would leave the file as is.

    Args:
      seeded: the state ``baudolo_seeded`` or ``baudolo_seed_apply`` returned.
      instance, database, username, password: the ``baudolo-seed`` arguments.

    Returns:
      True when the file is canonical and every row of this instance and
      database already carries these credentials.
    """
    name = _database(database)
    if not seeded["canonical"] or name is None:
        return False
    matches = [row for row in seeded["rows"] if row[0] == instance and row[1] == name]
    return bool(matches) and all(
        row[2] == username and row[3] == password for row in matches
    )


def baudolo_seed_apply(seeded, instance, database, username, password) -> dict:
    """The state after ``baudolo-seed`` ran with these arguments.

    Args:
      seeded: the state ``baudolo_seeded`` or ``baudolo_seed_apply`` returned.
      instance, database, username, password: the ``baudolo-seed`` arguments.

    Returns:
      dict shaped like the ``baudolo_seeded`` result, with every row of this
      instance and database carrying the credentials, or one row appended
      when there was none; a non-canonical state stays non-canonical.
    """
    name = _database(database)
    if not seeded["canonical"] or name is None:
        return {"canonical": False, "rows": []}
    rows = [list(row) for row in seeded["rows"]]
    matched = False
    for row in rows:
        if row[0] == instance and row[1] == name:
            row[2:] = [username, password]
            matched = True
    if not matched:
        rows.append([instance, name, username, password])
    return {"canonical": True, "rows": rows}


class FilterModule:
    def filters(self):
        return {
            "baudolo_seeded": baudolo_seeded,
            "baudolo_seed_current": baudolo_seed_current,
            "baudolo_seed_apply": baudolo_seed_apply,
        }
