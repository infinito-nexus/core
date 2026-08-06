"""Lint guard: rsync invocations MUST NOT carry ``-b`` / ``--backup``.

Every backup path here writes a generation more than once: baudolo copies
each volume hot and again after stopping the container, and
``pull_specific_host.py`` retries the same command into the same
destination. ``--backup`` turns that second write into a rename, so a file
the source deleted or replaced survives as ``name~`` beside the real one and
is restored into live data.

Lucene resolves its current commit by parsing *every* file starting with
``segments`` as a radix-36 generation, so one ``segments_3~`` is enough to
make a shard unopenable. ``--link-dest`` already provides the incrementals.

Suppress on a per-line basis with a same-line ``# nocheck: rsync-backup --
<reason>`` marker.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import read_text

from . import PROJECT_ROOT

_SCANNED_SUFFIXES = (".py", ".sh", ".j2", ".yml", ".yaml")
_SELF_REL = (
    Path(__file__).resolve().relative_to(Path(PROJECT_ROOT).resolve()).as_posix()
)
_LONG_RE = re.compile(r"(?<![\w-])--backup(?![\w-])")
_SHORT_RE = re.compile(r"(?<![\w-])-[a-zA-Z]*b[a-zA-Z]*(?![\w-])")
_RSYNC_RE = re.compile(r"(?<![\w./-])rsync(?![\w-])")
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    detail: str


def _git_ls_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "-c", "safe.directory=*", "-C", str(PROJECT_ROOT), "ls-files"],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _offending_flag(line: str) -> str | None:
    """Name the backup flag on a line, or None when it carries none.

    Args:
        line: one source line already known to mention rsync.
    """
    if _LONG_RE.search(line):
        return "--backup"
    for token in re.findall(r"(?<![\w-])-[a-zA-Z]+(?![\w-])", line):
        if "b" in token[1:] and _SHORT_RE.fullmatch(token):
            return token
    return None


def _scan_file(path: Path) -> list[Violation]:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError) as exc:
        return [Violation(rel, 0, str(exc))]

    violations: list[Violation] = []
    rsync_window = 0
    for idx, raw in enumerate(text.splitlines(), 1):
        if _RSYNC_RE.search(raw):
            rsync_window = 8
        elif rsync_window:
            rsync_window -= 1
        else:
            continue
        if _NOCHECK_RE.search(raw):
            continue
        flag = _offending_flag(raw)
        if flag:
            violations.append(
                Violation(
                    rel,
                    idx,
                    f"`{flag}` keeps a `name~` twin of every file a later pass "
                    "replaces or deletes; drop it and rely on --link-dest, or "
                    "suppress with `# nocheck: rsync-backup -- <reason>`",
                )
            )
    return violations


def _scan_targets() -> list[Path]:
    return [
        PROJECT_ROOT / rel
        for rel in _git_ls_files()
        if rel.endswith(_SCANNED_SUFFIXES) and rel != _SELF_REL
    ]


class TestNoRsyncBackupFlag(unittest.TestCase):
    def test_no_rsync_call_keeps_backup_twins(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no files found to scan")
        all_violations: list[Violation] = []
        for path in targets:
            all_violations.extend(_scan_file(path))
        if all_violations:
            grouped: dict[str, list[Violation]] = {}
            for v in all_violations:
                grouped.setdefault(v.file, []).append(v)
            lines = [
                (
                    f"rsync --backup in {len(all_violations)} place(s) across "
                    f"{len(grouped)} file(s):"
                ),
                "",
                (
                    "A backup generation is written more than once (hot pass "
                    "then cold pass, or a retry into the same destination). "
                    "`--backup` preserves the superseded file as `name~`, "
                    "which restores into live data and breaks any format that "
                    "enumerates its own directory."
                ),
                "",
                "Offenders:",
            ]
            for f, vs in sorted(grouped.items()):
                lines.append(f"  {f}:")
                lines.extend(f"    line {v.line_no}: {v.detail}" for v in vs)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
