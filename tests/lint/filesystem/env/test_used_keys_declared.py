"""Every INFINITO_* used in `.sh` / `.py` must be declared as a default.

Defaults live in ``default.env`` (the SPOT for static values) and
in the handler modules under ``utils/env/handlers/`` (which apply
dynamic defaults via ``setdefault``). Together they form the registry
of valid INFINITO_* keys.

This test scans every shell and Python source file for INFINITO_*
references and fails when a referenced key has no corresponding entry
in either the static file or a handler module. Such a key would reach
the consumer unset, and a bare read would crash with KeyError / set -u.

Allowed reference shapes (sampled, not exhaustive):

* shell:  ``${INFINITO_VAR}``, ``${INFINITO_VAR:?msg}``, ``${INFINITO_VAR:-}``
* python: ``os.environ["INFINITO_VAR"]``, ``os.environ.get("INFINITO_VAR")``,
          ``env.get("INFINITO_VAR")``, etc.

Suppress per line with a same-line ``# nocheck: <reason>`` marker. Use
it only for keys that legitimately stay registry-less (e.g. pure
bootstrap one-shots).
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import iter_non_ignored_files, read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_SH_REF_RE = re.compile(r"\$\{?(?P<key>INFINITO_[A-Z0-9_]+)")
_PY_LITERAL_RE = re.compile(r"[\"'](?P<key>INFINITO_[A-Z0-9_]+)[\"']")
_DEFAULT_ENV_KEY_RE = re.compile(r"^\s*(?P<key>INFINITO_[A-Z0-9_]+)\s*=")
_HANDLER_LITERAL_RE = re.compile(r"[\"'](?P<key>INFINITO_[A-Z0-9_]+)[\"']")
_NOCHECK_RE = re.compile(r"#\s*nocheck\b")

# These trees define the registry / document it; references in them
# describe the rule, they do not consume the keys.
_EXCLUDED_PREFIXES = (
    "tests/lint/",
    "utils/env/handlers/",
    "scripts/meta/env/python.sh",
    "default.env",
)


@dataclass(frozen=True)
class _Reference:
    file: str
    line_no: int
    key: str


def _registered_keys() -> set[str]:
    keys: set[str] = set()
    default_env = PROJECT_ROOT / "default.env"
    if default_env.is_file():
        for line in read_text(str(default_env)).splitlines():
            match = _DEFAULT_ENV_KEY_RE.match(line)
            if match is not None:
                keys.add(match.group("key"))

    python_detect = PROJECT_ROOT / "scripts" / "meta" / "env" / "python.sh"
    if python_detect.is_file():
        for line in read_text(str(python_detect)).splitlines():
            match = _DEFAULT_ENV_KEY_RE.match(line)
            if match is not None:
                keys.add(match.group("key"))

    handlers_dir = PROJECT_ROOT / "utils" / "env" / "handlers"
    for module in sorted(handlers_dir.glob("*.py")):
        if module.name == "__init__.py":
            continue
        text = read_text(str(module))
        for match in _HANDLER_LITERAL_RE.finditer(text):
            keys.add(match.group("key"))

    return keys


def _strip_comment(line: str) -> str:
    """Drop a trailing `# ...` comment so INFINITO_* names mentioned only in
    prose do not register as code references. Crude: a `#` inside a quoted
    string also truncates, which is fine since INFINITO_* references inside
    quoted strings stay intact in the kept prefix."""
    idx = line.find("#")
    return line if idx < 0 else line[:idx]


def _scan_with(path: Path, pattern: re.Pattern[str]) -> list[_Reference]:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    out: list[_Reference] = []
    for idx, line in enumerate(read_text(str(path)).splitlines(), start=1):
        if _NOCHECK_RE.search(line):
            continue
        code = _strip_comment(line)
        out.extend(_Reference(rel, idx, m.group("key")) for m in pattern.finditer(code))
    return out


def _scan_shell(path: Path) -> list[_Reference]:
    return _scan_with(path, _SH_REF_RE)


def _scan_python(path: Path) -> list[_Reference]:
    return _scan_with(path, _PY_LITERAL_RE)


def _scan_targets() -> tuple[list[Path], list[Path]]:
    sh: list[Path] = []
    py: list[Path] = []
    root_str = str(PROJECT_ROOT)
    for absolute in iter_non_ignored_files(root=root_str):
        rel = absolute.removeprefix(root_str + "/")
        if any(rel.startswith(prefix) for prefix in _EXCLUDED_PREFIXES):
            continue
        if rel.endswith(".sh"):
            sh.append(PROJECT_ROOT / rel)
        elif rel.endswith(".py"):
            py.append(PROJECT_ROOT / rel)
    return sh, py


class TestUsedKeysDeclared(unittest.TestCase):
    def test_every_referenced_infinito_key_is_registered(self) -> None:
        registered = _registered_keys()
        self.assertTrue(registered, "no INFINITO_* keys found in the registry")

        shell_files, python_files = _scan_targets()
        self.assertTrue(shell_files or python_files, "no .sh / .py files to scan")

        violations: list[_Reference] = []
        for path in shell_files:
            violations.extend(
                ref for ref in _scan_shell(path) if ref.key not in registered
            )
        for path in python_files:
            violations.extend(
                ref for ref in _scan_python(path) if ref.key not in registered
            )

        if not violations:
            return

        unique_keys = sorted({v.key for v in violations})
        grouped: dict[str, list[_Reference]] = {}
        for v in violations:
            grouped.setdefault(v.key, []).append(v)

        lines = [
            f"INFINITO_* keys referenced in code without a registry entry "
            f"({len(unique_keys)} unknown key(s) across {len(violations)} use site(s)):",
            "",
            "Add a default to default.env (and to the static-passthrough handler's STATIC_KEYS) for static values, or write a dedicated handler under utils/env/handlers/ that sets the key via eb.setdefault. Suppress per line with `# nocheck: <reason>` when the key legitimately stays registry-less.",
            "",
            "Unregistered keys:",
        ]
        for key in unique_keys:
            lines.append(f"  {key}:")
            lines.extend(f"    {ref.file}:{ref.line_no}" for ref in grouped[key])
        self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
