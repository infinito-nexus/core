"""Lint guard: every .py file (production AND tests) MUST route YAML
reads/writes through ``utils.cache.yaml`` instead of calling
``yaml.safe_load`` / ``yaml.safe_dump`` (and friends) directly.

Background
==========
``yaml.safe_load()`` / ``yaml.safe_dump()`` bypass the process-wide YAML
parse cache (``utils.cache.yaml.load_yaml`` / ``load_yaml_any`` /
``dump_yaml``). On a 250+ role tree the cumulative cost of repeated
parses is significant, and divergent loaders can return subtly different
shapes (one swallowing parse errors, another raising; one returning a
fresh dict, another a shared cached one). Routing every load through
``utils.cache.yaml`` keeps the process-wide cache shared and the loader
semantics consistent — including across the lint/integration/unit
test suites which can re-parse the same role-meta files dozens of times
during a single ``make test`` run.

Allowed
=======
* ``utils/cache/yaml.py``: IS the cache, MUST call ``yaml.safe_load`` /
  ``yaml.safe_dump`` directly.
* ``tasks/utils/migrate_meta_layout.py``: migration script that
  operates pre-migration on raw on-disk YAML; predates the cache by
  design.
* Tests that legitimately need raw YAML access (e.g. writing synthetic
  YAML to a tempdir and reading it back to validate parser behaviour)
  MUST opt out per call with ``# noqa: direct-yaml`` rather than
  silently bypassing the cache.

Detection
=========
AST-walks every ``.py`` file under the production trees (``utils/``,
``cli/``, ``plugins/``, ``filter_plugins/``, ``lookup_plugins/``,
``roles/``, ``scripts/``, ``tasks/``) AND under ``tests/`` and flags
any call to ``yaml.safe_load`` / ``yaml.safe_load_all`` /
``yaml.safe_dump`` / ``yaml.load`` / ``yaml.dump`` / ``yaml.dump_all``.
Aliased imports are tracked: ``import yaml as Y`` ⇒ ``Y.safe_load(...)``
is flagged; ``from yaml import safe_load`` ⇒ bare ``safe_load(...)`` is
flagged.

Plain attribute access without a call (``yaml.YAMLError`` for exception
typing, ``yaml.YAMLObject`` for class hierarchies) is NOT flagged. Only
call expressions are.

Per-line opt-out: add ``# nocheck: direct-yaml`` (case-insensitive)
on the line of the call, the line that opens the multi-line call,
OR anywhere on the same physical line in the source file. The lint
then skips that specific call while still flagging any other direct
yaml calls in the same file. Use this for legitimate exceptions
(custom Loader/Dumper subclasses, runtime-deployed scripts that lack
the project's ``utils/`` package on PYTHONPATH, etc.). Keep the
exemption next to the code it covers, not in this lint's allow-list.

Note: the canonical project marker for ``noqa|nocheck`` rules accepts
both keywords, but ``direct-yaml`` MUST use ``nocheck``. ``# noqa: …``
is parsed by ruff as a flake8 directive and triggers
``invalid-noqa-code`` warnings for non-flake8 rule keys; ``nocheck``
is the project-specific synonym ruff ignores. The marker grammar is
documented at ``docs/contributing/actions/testing/suppression.md``.

Caching
=======
File contents are routed through ``utils.cache.files.read_text`` so
multiple lint tests scanning the same source pay one read.
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

# `direct-yaml` opts out only via ``nocheck:`` markers. We deliberately
# do NOT accept the generic ``noqa:`` form here: ruff parses that form
# as a flake8 directive and warns about non-flake8 codes like
# ``direct-yaml``. ``nocheck`` is the project-specific synonym ruff
# ignores. This regex mirrors the ``nocheck`` half of
# ``utils.annotations.suppress._KEYWORD_RE``.
_NOCHECK_RE = re.compile(
    r"nocheck\s*:\s*([a-z0-9][a-z0-9\-]*(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*)",
    re.IGNORECASE,
)


_FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset(
    {
        "safe_load",
        "safe_load_all",
        "safe_dump",
        "safe_dump_all",
        "load",
        "load_all",
        "dump",
        "dump_all",
    }
)

_SCAN_DIRS: frozenset[str] = frozenset(
    {
        "utils",
        "cli",
        "plugins",
        "filter_plugins",
        "lookup_plugins",
        "roles",
        "scripts",
        "tasks",
        "tests",
    }
)


def _file_offenders(path: Path) -> list[str]:
    """Return ``[]`` if the file routes everything through the cache,
    or a list of human-readable ``line N: <call>`` strings for each
    forbidden direct yaml call.
    """
    try:
        src = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(src, filename=str(path))
    except SyntaxError:
        return []

    # Track names bound to the `yaml` module (`import yaml`, `import yaml as Y`).
    yaml_module_aliases: set[str] = set()
    # Track names bound to forbidden top-level functions
    # (`from yaml import safe_load`, `from yaml import safe_load as L`).
    direct_function_aliases: dict[str, str] = {}

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "yaml":
                    yaml_module_aliases.add(alias.asname or "yaml")
        elif isinstance(node, ast.ImportFrom) and node.module == "yaml":
            for alias in node.names:
                if alias.name in _FORBIDDEN_FUNCTIONS:
                    direct_function_aliases[alias.asname or alias.name] = alias.name

    # The marker may appear on the call's own line OR, for multi-line
    # calls, on any line spanned by the call expression.
    nocheck_lines: set[int] = set()
    for idx, line in enumerate(src.splitlines(), start=1):
        for match in _NOCHECK_RE.finditer(line):
            rules = {r.strip().lower() for r in match.group(1).split(",")}
            if "direct-yaml" in rules:
                nocheck_lines.add(idx)
                break

    def _is_suppressed(node: ast.Call) -> bool:
        start = node.lineno
        end = getattr(node, "end_lineno", node.lineno)
        return any(line in nocheck_lines for line in range(start, end + 1))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute):
            if (
                isinstance(func.value, ast.Name)
                and func.value.id in yaml_module_aliases
                and func.attr in _FORBIDDEN_FUNCTIONS
            ):
                if _is_suppressed(node):
                    continue
                offenders.append(
                    f"line {node.lineno}: {func.value.id}.{func.attr}(...)"
                )
        elif isinstance(func, ast.Name) and func.id in direct_function_aliases:
            if _is_suppressed(node):
                continue
            actual = direct_function_aliases[func.id]
            offenders.append(f"line {node.lineno}: {func.id}(...) [yaml.{actual}]")
    return offenders


def _scan_paths() -> list[Path]:
    """Iterate every production .py file via the shared file-walk cache."""
    out: list[Path] = []
    for s in iter_project_files(extensions=(".py",), exclude_tests=False):
        p = Path(s)
        try:
            rel = p.relative_to(PROJECT_ROOT)
        except ValueError:
            continue
        if not rel.parts or rel.parts[0] not in _SCAN_DIRS:
            continue
        out.append(p)
    return sorted(out)


class TestNoDirectYamlCalls(unittest.TestCase):
    """Every .py file (production AND tests) MUST go through utils.cache.yaml."""

    def test_no_direct_yaml_calls(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _scan_paths():
            issues = _file_offenders(path)
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} .py file(s) call yaml.safe_load / "
            f"yaml.safe_dump (or aliases) directly instead of routing through "
            f"utils.cache.yaml.{{load_yaml, load_yaml_any, dump_yaml}}:",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            lines.extend(f"      * {issue}" for issue in issues)
        lines.append("")
        lines.append(
            "Fix: replace `yaml.safe_load(path.read_text())` with "
            "`load_yaml_any(str(path), default_if_missing={})` (or "
            "`load_yaml` for strict mapping shape). Replace "
            "`yaml.safe_dump(data, path.open('w'))` with "
            "`dump_yaml(path, data)` from utils.cache.yaml."
        )
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
