"""Lint guard: `.sh` files MUST NOT declare absolute-path defaults.

A default like ``${BACKUP_KEY_PATH:-/tmp/swarm-nfs-backup.key}`` duplicates a
path contract that belongs in ``default.env`` (SPOT): every consumer carrying
its own copy drifts silently the moment one of them changes. This guard
covers every ALL-CAPS environment variable whose inline default starts with
``/`` and complements ``test_no_infinito_defaults`` (which forbids any
non-empty default for INFINITO_* keys).

Allowed in ``.sh``:

* Bare read: ``${SOME_PATH}``
* Required-loud: ``${SOME_PATH:?msg}`` (fail with hint when unset)
* Empty-default for ``set -u`` safety: ``${SOME_PATH:-}``
* Non-path defaults (numbers, command names): out of scope here

Forbidden:

* Inline path default: ``${SOME_PATH:-/abs/path}`` / ``${SOME_PATH-/abs/path}``
* Setdefault path: ``${SOME_PATH:=/abs/path}`` / ``${SOME_PATH=/abs/path}``
* Rewriting the same contract as a conditional assignment
  (``if [ -z "${SOME_PATH:-}" ]; then SOME_PATH=/abs/path; fi`` or
  ``SOME_PATH="${SOME_PATH:-}"; [ -n "$SOME_PATH" ] || SOME_PATH=/abs/path``)
  is the same violation in disguise and MUST NOT be used to dodge this guard.

Suppress on a per-line basis with a same-line ``# nocheck: <reason>`` marker,
only when the shell context genuinely cannot consume ``default.env``.
"""

from __future__ import annotations

import re
import subprocess
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_INLINE_PATH_DEFAULT_RE = re.compile(
    r"\$\{(?P<key>[A-Z_][A-Z0-9_]*)(?P<op>:-|:=|-|=)(?P<default>/[^}]*)\}",
)
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    rule: str
    detail: str


def _git_ls_files() -> list[str]:
    """List tracked files; ``safe.directory=*`` bypasses git's ownership
    check, which fails inside the dev container when the bind-mounted
    repo's UID does not match the container user."""
    out = subprocess.check_output(
        [
            "git",
            "-c",
            "safe.directory=*",
            "-C",
            str(PROJECT_ROOT),
            "ls-files",
        ],
        text=True,
    )
    return [line for line in out.splitlines() if line]


def _scan_file(path: Path) -> list[Violation]:
    violations: list[Violation] = []
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError) as exc:
        return [Violation(rel, 0, "read-error", str(exc))]

    for idx, raw in enumerate(text.splitlines(), 1):
        if _NOCHECK_RE.search(raw):
            continue

        for match in _INLINE_PATH_DEFAULT_RE.finditer(raw):
            key = match.group("key")
            op = match.group("op")
            default = match.group("default")
            violations.append(
                Violation(
                    rel,
                    idx,
                    "path-default",
                    f"${{{key}{op}{default}}} declares a shell-side path "
                    f"default; declare the default in default.env (SPOT) and "
                    f"read as bare ${{{key}}} or required ${{{key}:?msg}}",
                )
            )
    return violations


def _scan_targets() -> list[Path]:
    return [PROJECT_ROOT / rel for rel in _git_ls_files() if rel.endswith(".sh")]


class TestShellNoPathDefaults(unittest.TestCase):
    def test_shell_files_dont_declare_path_defaults(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no .sh files found to scan")
        all_violations: list[Violation] = []
        for path in targets:
            all_violations.extend(_scan_file(path))
        if all_violations:
            grouped: dict[str, list[Violation]] = {}
            for v in all_violations:
                grouped.setdefault(v.file, []).append(v)
            lines = [
                f"absolute-path defaults declared in .sh "
                f"({len(all_violations)} violations across "
                f"{len(grouped)} file(s)):",
                "",
                "Path defaults belong in default.env (SPOT); a shell-side copy drifts silently. Read bare ${VAR} or use ${VAR:?msg}; the empty form ${VAR:-} stays allowed for `set -u` safety. Do NOT dodge this guard by rewriting the default as a conditional assignment (`if [ -z ... ]; then VAR=/path; fi` or `[ -n ... ] || VAR=/path`) - that is the same second source of truth. Suppress per line with `# nocheck: <reason>` only when the context cannot consume default.env.",
                "",
                "Offenders:",
            ]
            for f, vs in sorted(grouped.items()):
                lines.append(f"  {f}:")
                lines.extend(f"    line {v.line_no} [{v.rule}]: {v.detail}" for v in vs)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
