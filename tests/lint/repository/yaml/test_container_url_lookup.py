"""Lint guard: build a container-network origin with ``container_url``.

A sibling container is reached at ``http://<entity name>:<internal port>``,
and that string was written out per call site: a literal protocol, an
``entity_name`` interpolation for the host, and a ``lookup('config', …,
'services.<key>.ports.internal.http')`` for the port. Three facts, repeated
nine times across seven roles, each needing its own
``# nocheck: literal-protocol-lookup`` because the sibling lint rightly
objects to a protocol glued in front of a lookup.

``lookup('container_url', application_id, service_key)`` holds all three.
The protocol is decided once, where the reason lives - a container network
speaks plaintext by construction, which is a property of the network and not
of the caller - so no call site carries a literal protocol for the other
lint to see, and the suppression markers disappear with it.

Detection is the shape itself: a protocol, an interpolation mentioning
``entity_name``, then a colon and a second interpolation. That is the
assembled origin and nothing else matches it.

Allowed
=======
``# nocheck: container-url-lookup`` on the line or the one above it, for an
origin this lookup genuinely cannot express - a port that is not
``ports.internal.http``, or a host that is not the application's entity.
"""

from __future__ import annotations

import re
import unittest
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

if TYPE_CHECKING:
    from collections.abc import Iterable

_RULE = "container-url-lookup"

_ASSEMBLED_ORIGIN_RE: re.Pattern[str] = re.compile(
    r"https?://\{\{[^}]*\bentity_name\b[^}]*\}\}\s*:\s*\{\{"
)

ROLES_DIR = PROJECT_ROOT / "roles"


def _suppressed_for_value(lines: list[str], idx: int) -> bool:
    """Whether the value starting at 1-based *idx* carries the marker.

    A wrapped value keeps its trailing comment on the last line while the
    offence is reported on the first, so the continuation lines count too.
    """
    if is_suppressed_at(lines, idx, _RULE):
        return True
    for following in range(idx + 1, len(lines) + 1):
        text = lines[following - 1]
        if not text[:1].isspace():
            return False
        if is_suppressed_at(lines, following, _RULE, mode="same-line"):
            return True
    return False


@lru_cache(maxsize=8192)
def _file_offenders(path: Path) -> tuple[str, ...]:
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return ()

    if "entity_name" not in text or "://" not in text:
        return ()

    lines = text.splitlines()
    offenders: list[str] = []
    for idx, line in enumerate(lines, start=1):
        if not _ASSEMBLED_ORIGIN_RE.search(line):
            continue
        if _suppressed_for_value(lines, idx):
            continue
        offenders.append(f"line {idx}: {line.strip()}")
    return tuple(offenders)


def _scan_paths() -> Iterable[Path]:
    for candidate in iter_project_files(exclude_tests=True, exclude_dirs=("docs",)):
        path = Path(candidate)
        try:
            rel = path.relative_to(ROLES_DIR)
        except ValueError:
            continue
        if any(segment in {"docs", "files"} for segment in rel.parts[:-1]):
            continue
        yield path


class TestContainerUrlLookup(unittest.TestCase):
    def test_no_hand_assembled_container_origin(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _scan_paths():
            issues = list(_file_offenders(path))
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        lines = [
            (
                f"{len(offenders)} file(s) assemble a container-network origin "
                f"by hand instead of asking for it:"
            ),
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {path.relative_to(PROJECT_ROOT)}:")
            lines.extend(f"      * {issue}" for issue in issues)
        lines.append("")
        lines.append(
            "Fix: {{ lookup('container_url', <application_id>, '<service key>') }}, "
            "which returns http://<entity name>:<services.<key>.ports.internal.http> "
            "and lets you append your own path. It also removes the "
            "'# nocheck: literal-protocol-lookup' the hand-written form needs, "
            f"because no literal protocol is left at the call site. Where the "
            f"origin genuinely cannot be expressed that way, mark the line "
            f"'# nocheck: {_RULE}' and say which part differs."
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
