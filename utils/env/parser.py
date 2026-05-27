"""Parse the project's `default.env`.

The format is the docker-compose `.env`-subset: flat `KEY=value` lines,
`#` for comments, optional surrounding double/single quotes for values
that contain whitespace or special characters. Anything more exotic
(nested mappings, multiline values, variable expansion) is rejected so
drift between the file and its consumers stays loud.

Comments are first-class: every `# ...` line directly above a key is
captured and surfaced via :func:`parse_static_env_with_comments`, so
the generator can preserve per-key documentation in the produced
``.env``.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.cache.files import read_text

if TYPE_CHECKING:
    from pathlib import Path

_LINE_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$")


def _parse_value(raw_value: str) -> str:
    value = raw_value
    # Strip trailing inline comment when value is not quoted.
    if value and value[0] not in ('"', "'"):
        value = value.split("#", 1)[0].rstrip()
    # Strip a matched pair of outer quotes and undo the writer's
    # `\\`/`\"` escaping (mirrors bash double-quote semantics for the
    # subset of values this parser is allowed to handle).
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        quote = value[0]
        value = value[1:-1]
        if quote == '"':
            value = value.replace('\\"', '"').replace("\\\\", "\\")
    return value


def parse_static_env(path: Path) -> dict[str, str]:
    """Return the `KEY: value` map declared in `path`."""
    values, _ = parse_static_env_with_comments(path)
    return values


def parse_static_env_with_comments(
    path: Path,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (`values`, `comments`) for the env-file at `path`.

    A key's comment is the most recent contiguous block of `# ...`
    lines directly above the `KEY=...` line, joined with single spaces.
    Section headers (`# --- ... ---`) are treated as separators: they
    reset the pending comment so the next key starts fresh, instead
    of inheriting the heading line as its own documentation.
    """
    values: dict[str, str] = {}
    comments: dict[str, str] = {}
    pending: list[str] = []
    for lineno, raw in enumerate(read_text(str(path)).splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            pending = []
            continue
        if stripped.startswith("#"):
            body = stripped.lstrip("#").strip()
            # Section dividers / banner blocks (`# --- ... ---`,
            # multi-paragraph file header) do not become per-key docs.
            if body.startswith("---") and body.endswith("---"):
                pending = []
                continue
            pending.append(body)
            continue
        match = _LINE_RE.match(stripped)
        if not match:
            raise ValueError(f"{path}:{lineno}: cannot parse line: {raw!r}")
        key, raw_value = match.group(1), match.group(2)
        values[key] = _parse_value(raw_value)
        if pending:
            comments[key] = " ".join(pending)
        pending = []
    return values, comments
