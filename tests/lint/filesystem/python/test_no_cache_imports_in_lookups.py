"""Lint guard: Ansible lookup plugins MUST reach the merged-config SPOT
through the lookup loader (``lookup('applications'|'config'|'domains'|'users')``)
instead of importing the merge functions from ``utils.cache``.

Background
==========
``utils.cache.applications.get_merged_applications`` (and the domain / user
equivalents) is the single merge implementation, surfaced to playbooks as the
``applications`` / ``config`` / ``domains`` / ``users`` lookups. A lookup
plugin that imports those merge functions re-runs the merge itself instead of
consuming the one SPOT view: it drifts from the play's resolved config and
reintroduces the manual-render trust-gotcha class (``templar.template`` no-ops
on untrusted strings in ansible 2.19+). Consumers reach the SPOT via
``ansible.plugins.loader.lookup_loader`` -- see
``plugins/lookup/compose_networks.py`` for the idiom::

    from ansible.plugins.loader import lookup_loader

    apps = lookup_loader.get(
        "applications", loader=self._loader, templar=self._templar
    ).run([], variables=variables)[0]

Scope
=====
Every ``.py`` under ``plugins/lookup/`` and ``roles/*/lookup_plugins/``.
``tests/`` is out of scope (fixtures legitimately build merged views).

Detection
=========
AST-flags ``from utils.cache.applications|domains|users import ...`` and
``import utils.cache.applications|domains|users``. The generic cache infra
(``utils.cache.base`` render helper, ``.yaml``, ``.files`` and the bare
``utils.cache`` package) is NOT a re-merge and stays allowed.

Per-line opt-out
================
The SPOT providers (``applications`` / ``config`` / ``applications_current_play``
/ ``users`` / ``domains``) and the raw-volume accessors (``volume`` / ``nginx``,
which must stay independent of the merge to avoid the render-guard re-entry
hole) legitimately import the cache. Each carries
``# nocheck: lookup-cache-import`` on the import line or the line directly
above it. The marker grammar lives in
``docs/contributing/actions/testing/suppression.md``.
"""

from __future__ import annotations

import ast
import unittest
from dataclasses import dataclass
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

_RULE = "lookup-cache-import"
_FORBIDDEN_MODULES: tuple[str, ...] = (
    "utils.cache.applications",
    "utils.cache.domains",
    "utils.cache.users",
)


def _in_scope(rel: str) -> bool:
    return rel.startswith("plugins/lookup/") or (
        rel.startswith("roles/") and "/lookup_plugins/" in rel
    )


def _module_forbidden(module: str | None) -> bool:
    if not module:
        return False
    return any(module == m or module.startswith(m + ".") for m in _FORBIDDEN_MODULES)


@dataclass(frozen=True)
class Finding:
    file: Path
    line: int
    module: str
    snippet: str

    def format(self, repo_root: Path) -> str:
        rel = self.file.relative_to(repo_root).as_posix()
        return f"{rel}:{self.line}: imports {self.module}: {self.snippet}"


def _scan_file(path: Path) -> list[Finding]:
    try:
        src = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    lines = src.splitlines()
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module
        elif isinstance(node, ast.Import):
            module = next(
                (a.name for a in node.names if _module_forbidden(a.name)), None
            )
        else:
            continue
        if not _module_forbidden(module):
            continue
        if is_suppressed_at(lines, node.lineno, _RULE, mode="same-or-above"):
            continue
        idx = node.lineno - 1
        snippet = lines[idx].strip()[:160] if 0 <= idx < len(lines) else ""
        findings.append(Finding(path, node.lineno, module, snippet))
    return findings


class TestNoCacheImportsInLookupPlugins(unittest.TestCase):
    def test_lookup_plugins_reach_spot_via_loader(self) -> None:
        repo_root = PROJECT_ROOT
        findings: list[Finding] = []
        for path_str in iter_project_files(extensions=(".py",), exclude_tests=True):
            rel = Path(path_str).relative_to(repo_root).as_posix()
            if not _in_scope(rel):
                continue
            findings.extend(_scan_file(Path(path_str)))

        if findings:
            formatted = "\n".join(f.format(repo_root) for f in findings)
            self.fail(
                f"{len(findings)} lookup-plugin import(s) pull the config-merge "
                f"functions from utils.cache instead of using the SPOT "
                f"lookups:\n{formatted}\n\n"
                "FIX: reach the merged config through the lookup loader:\n\n"
                "    from ansible.plugins.loader import lookup_loader\n"
                "    apps = lookup_loader.get('applications', loader=self._loader,\n"
                "        templar=self._templar).run([], variables=variables)[0]\n\n"
                "or lookup('config', app, path, default) for a single value. "
                "Only the SPOT providers and the raw-volume accessors may import "
                "the cache, each with an explicit `# nocheck: lookup-cache-import`."
            )


if __name__ == "__main__":
    unittest.main()
