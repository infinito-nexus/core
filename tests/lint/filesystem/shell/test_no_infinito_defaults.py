"""Lint guard: `.sh` files MUST NOT declare INFINITO_* defaults.

The single source of truth for INFINITO_* defaults is ``default.env``
(materialised into ``.env`` by ``make dotenv``). Shell-side defaults
duplicate that contract and drift silently the moment the static
default changes.

Allowed in ``.sh``:

* Bare read: ``${INFINITO_VAR}``
* Required-loud: ``${INFINITO_VAR:?msg}`` (fail with hint when unset)
* Empty-default for ``set -u`` safety: ``${INFINITO_VAR:-}`` /
  ``${INFINITO_VAR-}`` (presence check, not a value default)

Forbidden:

* Inline non-empty default: ``${INFINITO_VAR:-value}`` /
  ``${INFINITO_VAR-value}``
* Setdefault: ``${INFINITO_VAR:=value}`` / ``${INFINITO_VAR=value}``

Suppress on a per-line basis with a same-line ``# nocheck: <reason>``
marker. Use it only when the shell context genuinely cannot consume
``default.env`` (e.g. GHA workflow-input bridges, script-internal
overrides not exposed as a stack-wide variable).
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

# ``${INFINITO_VAR:-X}`` or ``${INFINITO_VAR-X}`` with X non-empty.
# The empty-default form ``${VAR:-}`` is the canonical ``set -u`` safe-read
# pattern and is intentionally allowed.
_INLINE_DEFAULT_RE = re.compile(
    r"\$\{(?P<key>INFINITO_[A-Z0-9_]+)(?P<op>:-|-)(?P<default>[^}]+)\}",
)
# ``${INFINITO_VAR:=X}`` or ``${INFINITO_VAR=X}`` (assign-if-unset).
# Any value is forbidden; this would persist into the surrounding shell.
_SETDEFAULT_RE = re.compile(
    r"\$\{(?P<key>INFINITO_[A-Z0-9_]+)(?P<op>:=|=)(?P<default>[^}]*)\}",
)
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")


@dataclass(frozen=True)
class Violation:
    file: str
    line_no: int
    rule: str
    detail: str


def _git_ls_files() -> list[str]:
    # ``safe.directory=*`` bypasses git's ownership check, which fails
    # inside the dev container when the bind-mounted repo's UID does
    # not match the container user.
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

        for match in _INLINE_DEFAULT_RE.finditer(raw):
            key = match.group("key")
            op = match.group("op")
            default = match.group("default")
            # ``${VAR:-}`` with an empty default is the safe-access idiom.
            if default == "":
                continue
            violations.append(
                Violation(
                    rel,
                    idx,
                    "inline-default",
                    f"${{{key}{op}{default}}} declares a shell-side default; "
                    f"move the default to default.env (SPOT) and read as "
                    f"bare ${{{key}}} or required ${{{key}:?msg}}",
                )
            )

        for match in _SETDEFAULT_RE.finditer(raw):
            key = match.group("key")
            op = match.group("op")
            default = match.group("default")
            violations.append(
                Violation(
                    rel,
                    idx,
                    "setdefault",
                    f"${{{key}{op}{default}}} sets a shell-side default; "
                    f"move it to default.env (SPOT)",
                )
            )
    return violations


def _scan_targets() -> list[Path]:
    return [PROJECT_ROOT / rel for rel in _git_ls_files() if rel.endswith(".sh")]


class TestShellNoInfinitoDefaults(unittest.TestCase):
    def test_shell_files_dont_declare_infinito_defaults(self) -> None:
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
                f"INFINITO_* defaults declared in .sh "
                f"({len(all_violations)} violations across "
                f"{len(grouped)} file(s)):",
                "",
                "INFINITO_* defaults belong in default.env (SPOT); the generated .env then carries them. Shell-side defaults are a second source that drifts silently. Read bare ${INFINITO_VAR} or use ${INFINITO_VAR:?msg}; the empty-form ${INFINITO_VAR:-} stays allowed for `set -u` safety. Suppress per line with `# nocheck: <reason>`.",
                "",
                "Offenders:",
            ]
            for f, vs in sorted(grouped.items()):
                lines.append(f"  {f}:")
                lines.extend(f"    line {v.line_no} [{v.rule}]: {v.detail}" for v in vs)
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
