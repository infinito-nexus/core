"""``API`` is reachable through its lookups only, never as a bare variable.

Rationale
=========
A bare ``API.github.client_id`` resolves against whatever the scope happens to
hold, and an inventory override replaces the declaration rather than merging
into it -- ``utils/cache/api.py`` carries the mechanism and the consequences.
``lookup('api', '<provider>.<key>')`` and ``lookup('api_enabled', '<provider>')``
merge the override over ``group_vars/all/18_api.yml``, so an override narrows
values and never the provider set. Routing every access through them also keeps
one place to change how credentials are sourced.

Scope
=====
Jinja in ``roles/``, ``group_vars/`` and ``inventories/``. An ``API:`` key
being *declared* is not an access; only a dereference inside ``{{ }}`` or
``{% %}`` is. Test fixtures legitimately build the bare form to exercise the
renderer, so ``tests/`` is out of scope.
"""

from __future__ import annotations

import re
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_SCOPES = ("roles", "group_vars", "inventories")
_SUFFIXES = (".yml", ".yaml", ".j2")
_JINJA_BLOCK = re.compile(r"\{\{(.*?)\}\}|\{%(.*?)%\}", re.DOTALL)
_BARE_API = re.compile(r"(?<![\w.'\"])API\s*[.\[]")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    expression: str


def _scoped_files() -> list[tuple[str, str]]:
    prefixes = tuple(f"{scope}/" for scope in _SCOPES)
    scoped: list[tuple[str, str]] = []
    for path, text in iter_project_files_with_content(
        extensions=_SUFFIXES, exclude_tests=True
    ):
        rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
        if rel.startswith(prefixes):
            scoped.append((rel, text))
    return sorted(scoped)


def _findings() -> list[Finding]:
    findings: list[Finding] = []
    for rel, text in _scoped_files():
        for match in _JINJA_BLOCK.finditer(text):
            expression = match.group(1) or match.group(2) or ""
            if not _BARE_API.search(expression):
                continue
            line = text.count("\n", 0, match.start()) + 1
            findings.append(Finding(rel, line, " ".join(expression.split())))
    return findings


class TestApiAccessedViaLookup(unittest.TestCase):
    def test_no_jinja_dereferences_api_directly(self) -> None:
        findings = _findings()

        if findings:
            self.fail(
                f"{len(findings)} expression(s) read 'API' as a bare variable, which "
                "breaks against an inventory that overrides only some providers:\n"
                + "\n".join(
                    f"  - {f.path}:{f.line}: {{{{ {f.expression} }}}}" for f in findings
                )
                + "\n\nRead the value with lookup('api', '<provider>.<key>') and gate "
                "on lookup('api_enabled', '<provider>')."
            )

    def test_the_scan_reaches_jinja_in_every_scope(self) -> None:
        """A suffix or scope typo would make the rule above pass forever."""
        scanned = _scoped_files()
        for scope in _SCOPES:
            with self.subTest(scope=scope):
                blocks = sum(
                    len(_JINJA_BLOCK.findall(text))
                    for rel, text in scanned
                    if rel.startswith(f"{scope}/")
                )
                self.assertTrue(blocks, f"no Jinja found under {scope}/")

    def test_the_pattern_separates_a_dereference_from_a_declaration(self) -> None:
        self.assertTrue(_BARE_API.search("API.github.client_id | length"))
        self.assertTrue(_BARE_API.search("API['github']"))
        self.assertFalse(_BARE_API.search("lookup('api', 'github.client_id')"))
        self.assertFalse(_BARE_API.search("LITELLM_API.url"))
        self.assertFalse(_BARE_API.search("item.API.key"))


if __name__ == "__main__":
    unittest.main()
