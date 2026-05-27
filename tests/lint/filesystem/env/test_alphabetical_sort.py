"""Env files (`*.env`, `*.env.j2`) must list keys in ASC order."""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_KEY_RE = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")
# Jinja2 control flow makes line ordering load-bearing; skip files that use it.
_JINJA_BLOCK_RE = re.compile(r"\{%")


@dataclass(frozen=True)
class _Entry:
    line_no: int
    key: str


def _entries_in(path: Path) -> list[_Entry] | None:
    raw = read_text(str(path))
    if _JINJA_BLOCK_RE.search(raw):
        return None
    out: list[_Entry] = []
    for index, line in enumerate(raw.splitlines(), start=1):
        match = _KEY_RE.match(line)
        if match is None:
            continue
        out.append(_Entry(index, match.group("key")))
    return out


def _scan_targets() -> list[Path]:
    return [
        PROJECT_ROOT / rel
        for rel in iter_non_ignored_files(root=str(PROJECT_ROOT))
        if rel.endswith((".env", ".env.j2"))
    ]


class TestEnvFilesAlphabetical(unittest.TestCase):
    def test_env_entries_sorted_ascending(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no env files found to scan")

        violations: list[str] = []
        for path in targets:
            entries = _entries_in(path)
            if entries is None or len(entries) < 2:
                continue
            keys = [e.key for e in entries]
            sorted_keys = sorted(keys)
            if keys == sorted_keys:
                continue
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            for entry, expected in zip(entries, sorted_keys, strict=True):
                if entry.key != expected:
                    violations.append(
                        f"  {rel}:{entry.line_no}: {entry.key} (expected {expected})"
                    )
                    break

        if violations:
            self.fail(
                "Env files must list keys in ASC order "
                f"({len(violations)} file(s) out of order):\n" + "\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
