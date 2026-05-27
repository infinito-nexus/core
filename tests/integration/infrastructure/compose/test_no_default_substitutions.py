"""Compose files MUST NOT carry inline default values.

Pattern enforcement: every variable substitution in ``compose.yml``,
``compose/*.yml``, and every ``roles/<role>/templates/compose*.yml.j2``
MUST be either ``${VAR}`` (bare) or ``${VAR:?...}`` (required, fail
loud with a hint). Inline defaults like ``${VAR:-fallback}`` or
``${VAR-fallback}`` are FORBIDDEN.

Why:

* **Ambiguity** -- when a compose file silently falls back to an
  inline default, the operator cannot tell from the rendered stack
  which value won (the env-file, the env override, or the compose
  default). Debugging the resulting drift is painful.
* **Single source of truth** -- the project keeps the canonical
  default for every variable in ``default.env`` (consumed by
  ``make dotenv`` into ``.env``). Inline compose defaults duplicate
  that contract in a second place and drift the moment the static
  default changes.

Fix when this test fails:

* Move the default to ``default.env`` so ``make dotenv`` materialises
  it into ``.env`` (which Docker Compose auto-loads).
* Replace the inline ``${VAR:-fallback}`` with ``${VAR:?Run 'make dotenv'
  to generate the .env single source of truth}`` so the failure mode
  becomes loud when ``.env`` is missing or stale.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

# Match ${VAR:-...} OR ${VAR-...} (POSIX-default-when-unset/empty
# vs. only-when-unset). Both are equally forbidden -- the project
# rule is "no inline defaults at all".
_DEFAULT_SUB_RE = re.compile(r"\$\{[A-Za-z_][A-Za-z0-9_]*(:-|-)[^}]*\}")
_KEY_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(:-|-)")


@dataclass(frozen=True)
class Finding:
    file: str
    line_no: int
    snippet: str
    var_name: str


def _scan_targets() -> list[Path]:
    targets: list[Path] = []
    root = PROJECT_ROOT

    root_compose = root / "compose.yml"
    if root_compose.is_file():
        targets.append(root_compose)
    compose_dir = root / "compose"
    if compose_dir.is_dir():
        targets.extend(sorted(compose_dir.glob("*.yml")))
        targets.extend(sorted(compose_dir.glob("*.yml.j2")))
    roles_dir = root / "roles"
    if roles_dir.is_dir():
        targets.extend(sorted(roles_dir.glob("*/templates/compose*.yml")))
        targets.extend(sorted(roles_dir.glob("*/templates/compose*.yml.j2")))
    return targets


def _scan_file(path: Path) -> list[Finding]:
    findings: list[Finding] = []
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return findings
    for idx, raw in enumerate(text.splitlines(), 1):
        for match in _DEFAULT_SUB_RE.finditer(raw):
            key_match = _KEY_RE.search(match.group(0))
            var_name = key_match.group(1) if key_match else "?"
            findings.append(
                Finding(
                    file=rel,
                    line_no=idx,
                    snippet=match.group(0),
                    var_name=var_name,
                )
            )
    return findings


class TestComposeNoDefaultSubstitutions(unittest.TestCase):
    def test_compose_files_have_no_inline_defaults(self) -> None:
        targets = _scan_targets()
        self.assertTrue(targets, "no compose files found to scan")
        all_findings: list[Finding] = []
        for path in targets:
            all_findings.extend(_scan_file(path))
        if all_findings:
            grouped: dict[str, list[Finding]] = {}
            for f in all_findings:
                grouped.setdefault(f.file, []).append(f)
            lines = [
                f"Compose files MUST NOT carry inline `${{VAR:-default}}` or "
                f"`${{VAR-default}}` substitutions ({len(all_findings)} found "
                f"across {len(grouped)} file(s))."
            ]
            lines.append("")
            lines.append(
                "Inline defaults make the effective value ambiguous and "
                "duplicate the SPOT that default.env owns. Move the "
                "default into default.env and replace the substitution "
                "with ${VAR:?Run 'make dotenv' to generate the .env single "
                "source of truth}."
            )
            lines.append("")
            lines.append("Offenders:")
            for f, items in sorted(grouped.items()):
                lines.append(f"  {f}:")
                lines.extend(
                    f"    line {item.line_no} [{item.var_name}]: {item.snippet}"
                    for item in items
                )
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
