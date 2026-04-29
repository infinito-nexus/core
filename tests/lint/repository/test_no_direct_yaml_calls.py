"""Lint guard: production .py files MUST route YAML reads/writes through
``utils.cache.yaml`` instead of calling ``yaml.safe_load`` /
``yaml.safe_dump`` (and friends) directly.

Background
==========
``yaml.safe_load()`` / ``yaml.safe_dump()`` bypass the process-wide YAML
parse cache (``utils.cache.yaml.load_yaml`` / ``load_yaml_any`` /
``dump_yaml``). On a 250+ role tree the cumulative cost of repeated
parses is significant, and divergent loaders can return subtly different
shapes (one swallowing parse errors, another raising; one returning a
fresh dict, another a shared cached one). Routing every load through
``utils.cache.yaml`` keeps the process-wide cache shared and the loader
semantics consistent.

Allowed
=======
* ``utils/cache/yaml.py`` — IS the cache, MUST call ``yaml.safe_load`` /
  ``yaml.safe_dump`` directly.
* ``tasks/utils/migrate_meta_layout.py`` — migration script that
  operates pre-migration on raw on-disk YAML; predates the cache by
  design.
* ``tests/`` — test fixtures may legitimately write synthetic YAML to
  tempdirs and read it back. NOT scanned.

Detection
=========
AST-walks every ``.py`` file under the production trees (``utils/``,
``cli/``, ``plugins/``, ``filter_plugins/``, ``lookup_plugins/``,
``roles/``, ``scripts/``, ``tasks/``) and flags any call to
``yaml.safe_load`` / ``yaml.safe_load_all`` / ``yaml.safe_dump`` /
``yaml.load`` / ``yaml.dump`` / ``yaml.dump_all``. Aliased imports are
tracked: ``import yaml as Y`` ⇒ ``Y.safe_load(...)`` is flagged;
``from yaml import safe_load`` ⇒ bare ``safe_load(...)`` is flagged.

Plain attribute access without a call (``yaml.YAMLError`` for exception
typing, ``yaml.YAMLObject`` for class hierarchies) is NOT flagged —
only call expressions are.

Per-line opt-out: add ``# noqa: direct-yaml`` (case-insensitive) on the
line of the call, the line that opens the multi-line call, OR anywhere
on the same physical line in the source file. The lint then skips that
specific call while still flagging any other direct yaml calls in the
same file. Use this for legitimate exceptions (custom Loader/Dumper
subclasses, runtime-deployed scripts that lack the project's
``utils/`` package on PYTHONPATH, etc.) — keep the exemption next to
the code it covers, not in this lint's allow-list.

Caching
=======
File contents are routed through ``utils.cache.files.read_text`` so
multiple lint tests scanning the same source pay one read.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text


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
    }
)

# Marker comment that opts a single call out of the lint. Match is
# case-insensitive and may appear anywhere on the call's physical line
# (or any line spanned by a multi-line call). The cache implementation
# itself, the migration script, vault-aware loaders/dumpers and any
# runtime-deployed scripts opt out via this marker — there is no
# central exemption list.
_NOQA_MARKER: str = "noqa: direct-yaml"


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
        elif isinstance(node, ast.ImportFrom):
            if node.module == "yaml":
                for alias in node.names:
                    if alias.name in _FORBIDDEN_FUNCTIONS:
                        direct_function_aliases[alias.asname or alias.name] = alias.name

    # Build a set of line numbers (1-based) carrying the noqa marker.
    # The marker may appear on the call's own line OR — for multi-line
    # calls — on any line spanned by the call expression.
    noqa_lines: set[int] = {
        idx
        for idx, line in enumerate(src.splitlines(), start=1)
        if _NOQA_MARKER in line.lower()
    }

    def _is_noqa(node: ast.Call) -> bool:
        start = node.lineno
        end = getattr(node, "end_lineno", node.lineno)
        return any(line in noqa_lines for line in range(start, end + 1))

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
                if _is_noqa(node):
                    continue
                offenders.append(
                    f"line {node.lineno}: {func.value.id}.{func.attr}(...)"
                )
        elif isinstance(func, ast.Name):
            if func.id in direct_function_aliases:
                if _is_noqa(node):
                    continue
                actual = direct_function_aliases[func.id]
                offenders.append(f"line {node.lineno}: {func.id}(...) [yaml.{actual}]")
    return offenders


def _scan_paths() -> list[Path]:
    """Iterate every production .py file via the shared file-walk cache."""
    out: list[Path] = []
    for s in iter_project_files(extensions=(".py",), exclude_tests=True):
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
    """Production .py files MUST go through utils.cache.yaml."""

    def test_no_direct_yaml_calls_in_production_code(self) -> None:
        offenders: dict[Path, list[str]] = {}
        for path in _scan_paths():
            issues = _file_offenders(path)
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        rel = lambda p: p.relative_to(PROJECT_ROOT)  # noqa: E731
        lines = [
            f"{len(offenders)} production .py file(s) call yaml.safe_load / "
            f"yaml.safe_dump (or aliases) directly instead of routing through "
            f"utils.cache.yaml.{{load_yaml, load_yaml_any, dump_yaml}}:",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            for issue in issues:
                lines.append(f"      * {issue}")
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
