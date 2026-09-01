"""Write a single ``bond`` scalar back into a role's ``meta/services.yml``.

The file is edited line by line rather than parsed and re-dumped: these files
carry ``# nocheck:`` directives and hand-tuned ordering that a YAML round-trip
would drop.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from pathlib import Path

_TOP_KEY = re.compile(r"^(?P<key>[^\s#][^:]*):\s*(?:#.*)?$")
_BOND = re.compile(r"^(?P<lead>\s*bond:\s*)(?P<value>[^#]*?)(?P<tail>\s*#.*)?$")


class EditError(Exception):
    """Raised when the requested bond cannot be written."""


def parse_bond(raw: str) -> float | None:
    """Return the bond a user typed, or None when they cleared the field."""
    text = str(raw).strip()
    if text in ("", "-", "·"):
        return None
    try:
        value = float(text)
    except ValueError as exc:
        raise EditError(f"not a number: {raw!r}") from exc
    if not 0.0 <= value <= 1.0:
        raise EditError(f"bond must be between 0 and 1, got {value:g}")
    return value


def _block(lines: list[str], key: str) -> tuple[int, int]:
    """Return the half-open line range of the top-level ``key`` mapping."""
    start = -1
    for index, line in enumerate(lines):
        match = _TOP_KEY.match(line)
        if match is None:
            continue
        if start < 0:
            if match.group("key").strip() == key:
                start = index
            continue
        return start, index
    if start < 0:
        raise EditError(f"no top-level entry {key!r}")
    return start, len(lines)


def set_bond(roles_dir: Path, role: str, service_key: str, bond: float | None) -> str:
    """Set, or with ``bond=None`` remove, ``<service_key>.bond`` in ``role``.

    Args:
        roles_dir: directory holding the role directories.
        role: the consumer role whose file declares the bond.
        service_key: the top-level key inside that role's services file.
        bond: the new value, or None to drop the declaration entirely.

    Returns:
        The value as it now stands in the file, or "" when it was removed.
    """
    path = roles_dir / role / ROLE_FILE_META_SERVICES
    if not path.is_file():
        raise EditError(f"no such file: {path}")

    raw = path.read_text(
        encoding="utf-8"
    )  # nocheck: cache-read — a cached read would serve the text from before the previous edit and silently revert it
    lines = raw.splitlines(keepends=True)
    start, end = _block(lines, service_key)

    target = next(
        (i for i in range(start + 1, end) if _BOND.match(lines[i].rstrip("\n"))), -1
    )
    if bond is None:
        if target < 0:
            return ""
        del lines[target]
    else:
        text = f"{bond:g}"
        if target < 0:
            indent = next(
                (
                    line[: len(line) - len(line.lstrip())]
                    for line in lines[start + 1 : end]
                    if line.strip() and not line.lstrip().startswith("#")
                ),
                "  ",
            )
            lines.insert(start + 1, f"{indent}bond: {text}\n")
        else:
            match = _BOND.match(lines[target].rstrip("\n"))
            if match is None:
                raise EditError(f"cannot rewrite {lines[target]!r}")
            lines[target] = f"{match['lead']}{text}{match['tail'] or ''}\n"

    path.write_text("".join(lines), encoding="utf-8")
    return "" if bond is None else f"{bond:g}"
