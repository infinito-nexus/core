"""Integration test: every defined lookup plugin must be referenced somewhere.

For every ``plugins/lookup/<name>.py`` that defines a ``LookupModule`` class,
verify that the lookup is actually consumed. Three invocation styles count
as real usage:

- ``lookup('<name>', ...)`` — the canonical Jinja/YAML form.
- ``query('<name>', ...)`` — the list-returning variant; equivalent to
  ``lookup(..., wantlist=True)``.
- ``from plugins.lookup.<name> import ...`` — direct Python import of the
  plugin's internals (e.g. ``utils/runtime_data.py`` embeds several
  ``LookupModule`` classes as regular helpers instead of dispatching
  through Ansible).

Mirrors ``tests/integration/filters/test_usage.py`` in spirit and uses the
same inverted-scan approach (one pass over all project files, a single
alternation regex matching every defined lookup name).

"Used in tests only" counts as failure: lookups shipped in ``plugins/lookup/``
must be called from production code (roles, tasks, group_vars, templates,
playbooks, or other plugins) — not just from test fixtures.
"""

from __future__ import annotations

import ast
import os
import re
import unittest
from pathlib import Path
from typing import Dict, List, Set

from utils.cache.files import iter_project_files, read_text


PROJECT_ROOT = Path(__file__).resolve().parents[3]
LOOKUP_PLUGINS_DIR = PROJECT_ROOT / "plugins" / "lookup"

# Extensions we consider capable of invoking a lookup.
USAGE_EXTS = (".yml", ".yaml", ".j2", ".jinja2", ".tmpl", ".py")


def _defines_lookup_module(path: Path) -> bool:
    """Return True if the module defines ``class LookupModule`` at top level.

    Ansible discovers every lookup plugin by filename, but only files that
    declare a ``LookupModule`` class are actual lookups. Helper modules
    without that class (should any appear) must not be treated as lookups.
    """
    try:
        tree = ast.parse(read_text(str(path)), filename=str(path))
    except (SyntaxError, OSError, UnicodeDecodeError):
        return False
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "LookupModule":
            return True
    return False


def collect_defined_lookups() -> Dict[str, Path]:
    """Return mapping ``{lookup_name: plugin_path}`` for all discovered plugins."""
    defined: Dict[str, Path] = {}
    if not LOOKUP_PLUGINS_DIR.is_dir():
        return defined
    for entry in sorted(LOOKUP_PLUGINS_DIR.iterdir()):
        if entry.suffix != ".py" or entry.name == "__init__.py":
            continue
        if not _defines_lookup_module(entry):
            continue
        defined[entry.stem] = entry.resolve()
    return defined


def _scan_lookup_usage(
    defined: Dict[str, Path],
) -> Dict[str, Dict[str, bool]]:
    """Single-pass inverted scan for ``lookup('name', ...)`` / ``query('name', ...)``.

    Complexity: O(M_files * 1_master_regex) rather than O(N_lookups * M_files).
    The combined regex carries alternation over every defined lookup name and
    covers both ``lookup(...)`` and ``query(...)`` invocation forms.
    """
    state: Dict[str, Dict[str, bool]] = {
        name: {"used_any": False, "used_outside": False} for name in defined
    }
    if not defined:
        return state

    escaped = [re.escape(name) for name in defined]
    name_alt = "(" + "|".join(escaped) + ")"
    # Match lookup('name'… / query('name'… / from plugins.lookup.name import
    # Arbitrary whitespace inside the call, both quote styles, and the Python
    # import form that ``utils/runtime_data.py`` uses to embed a LookupModule
    # directly.
    invoke_pat = re.compile(r"(?:lookup|query)\(\s*['\"]" + name_alt + r"['\"]")
    import_pat = re.compile(r"from\s+plugins\.lookup\." + name_alt + r"\s+import\b")

    tests_prefix = str(PROJECT_ROOT / "tests") + os.sep
    defined_paths: Set[str] = {str(p) for p in defined.values()}

    for path in iter_project_files(extensions=USAGE_EXTS):
        # Skip the plugin's own definition file — docstrings contain example
        # invocations of the same lookup and would otherwise register as
        # self-usage.
        resolved = os.path.realpath(path)
        if resolved in defined_paths:
            continue

        try:
            content = read_text(path)
        except (OSError, UnicodeDecodeError):
            continue

        is_in_tests = path.startswith(tests_prefix)
        for pat in (invoke_pat, import_pat):
            for match in pat.finditer(content):
                name = match.group(1)
                s = state[name]
                s["used_any"] = True
                if not is_in_tests:
                    s["used_outside"] = True

    return state


class TestLookupDefinitionsAreUsed(unittest.TestCase):
    """Every lookup plugin under ``plugins/lookup/`` must be invoked by name
    via ``lookup('<name>', ...)`` or ``query('<name>', ...)`` somewhere outside
    the tests directory. Shipping an unused lookup is a maintenance hazard —
    it stays in the module search path, increases cognitive load when
    browsing plugins, and rots silently when the rest of the codebase evolves.
    """

    def test_every_defined_lookup_is_used(self) -> None:
        defined = collect_defined_lookups()
        self.assertTrue(
            defined,
            "No lookup plugins found under plugins/lookup/; check PROJECT_ROOT.",
        )

        state = _scan_lookup_usage(defined)

        unused: List[tuple[str, Path, str]] = []
        for name in sorted(defined):
            s = state[name]
            if not s["used_any"]:
                unused.append((name, defined[name], "not used anywhere"))
            elif not s["used_outside"]:
                unused.append((name, defined[name], "only used in tests"))

        if unused:
            lines = ["The following lookup plugins are defined but unused:"]
            for name, path, reason in unused:
                rel = path.relative_to(PROJECT_ROOT).as_posix()
                lines.append(f"- '{name}' defined in {rel} → {reason}")
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
