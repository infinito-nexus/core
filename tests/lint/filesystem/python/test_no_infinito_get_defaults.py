"""Lint guard: `.py` files MUST NOT declare INFINITO_* defaults in `.get(KEY, default)`.

The single source of truth for INFINITO_* defaults is ``default.env``
(materialised into ``.env`` by ``make dotenv`` and applied as
``setdefault`` by the handler builders in ``utils/env/handlers/``).
Hardcoded fallbacks in Python contradict that contract -- if the
default.env value drifts, the Python copy silently keeps the old one.

Allowed:

* Bare read: ``os.environ.get("INFINITO_VAR")`` (returns ``None`` when unset)
* Required-loud: ``os.environ["INFINITO_VAR"]`` (raises ``KeyError`` when unset)

Forbidden:

* Any default at all, including the empty string:
  ``os.environ.get("INFINITO_VAR", "")``,
  ``os.environ.get("INFINITO_VAR", "1")``,
  ``env.get("INFINITO_VAR", DEFAULT)``, etc.

Suppress per line with a same-line ``# nocheck: <reason>`` marker.
Use it only when the call genuinely cannot consume ``default.env``
(e.g. bootstrap code that runs before the env loader).
"""

from __future__ import annotations

import ast
import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_INFINITO_KEY_RE = re.compile(r"^INFINITO_[A-Z0-9_]+$")
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")


@dataclass(frozen=True)
class _Violation:
    file: str
    line_no: int
    key: str
    default_repr: str


def _scan_file(path: Path) -> list[_Violation]:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
        tree = ast.parse(text, filename=rel)
    except (OSError, UnicodeDecodeError, SyntaxError):
        return []

    raw_lines = text.splitlines()
    violations: list[_Violation] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "get"):
            continue
        if len(node.args) < 2:
            continue
        key_node = node.args[0]
        if not (isinstance(key_node, ast.Constant) and isinstance(key_node.value, str)):
            continue
        if not _INFINITO_KEY_RE.match(key_node.value):
            continue
        default_node = node.args[1]
        # Allow per-line `# nocheck:` suppression on any physical line the
        # call spans (autoformat may have split a one-liner across the
        # opening paren, the args, and the closing paren).
        line_no = node.lineno
        end_line_no = getattr(node, "end_lineno", line_no) or line_no
        if any(
            1 <= n <= len(raw_lines) and _NOCHECK_RE.search(raw_lines[n - 1])
            for n in range(line_no, end_line_no + 1)
        ):
            continue
        violations.append(
            _Violation(
                rel,
                line_no,
                key_node.value,
                ast.unparse(default_node),
            )
        )

    return violations


def _scan_targets() -> list[Path]:
    return [
        PROJECT_ROOT / rel
        for rel in iter_non_ignored_files(root=str(PROJECT_ROOT))
        if rel.endswith(".py")
    ]


class TestPythonNoInfinitoGetDefaults(unittest.TestCase):
    def test_python_files_dont_declare_infinito_get_defaults(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no .py files found to scan")

        violations: list[_Violation] = []
        for path in targets:
            violations.extend(_scan_file(path))

        if not violations:
            return

        grouped: dict[str, list[_Violation]] = {}
        for v in violations:
            grouped.setdefault(v.file, []).append(v)
        lines = [
            f"INFINITO_* defaults declared in `.get(KEY, default)` "
            f"({len(violations)} violations across {len(grouped)} file(s)):",
            "",
            "INFINITO_* defaults belong in default.env (SPOT); the handler builders in utils/env/handlers/ then apply them via setdefault. Use `os.environ.get(KEY)` (None when unset) or `os.environ[KEY]` (loud KeyError) instead -- the empty-string fallback is also forbidden because it silently masks an unset key. Suppress per line with `# nocheck: <reason>`.",
            "",
            "Offenders:",
        ]
        for f, vs in sorted(grouped.items()):
            lines.append(f"  {f}:")
            lines.extend(
                f"    line {v.line_no}: {v.key} default={v.default_repr}" for v in vs
            )
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
