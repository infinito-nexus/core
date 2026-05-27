"""Lint that every variable defined in
`roles/<role>/vars/main.yml`, `roles/<role>/defaults/main.yml`, or
`group_vars/**/*.yml` is referenced by at least one project
`.yml` / `.yaml` / `.j2` file.

Catches drift where a flag like `<ROLE>_<FEATURE>_ENABLED` was once
declared and is no longer consumed — the value gets rendered for
nothing and silently rots in the repo.

Failure modes are aggregated into a single `self.fail` listing every
unused variable and the file/line where it is defined.

Companion lint to
[test_vars_usage_in_yaml.py](./test_vars_usage_in_yaml.py), which
covers the orthogonal "task-local `vars:` block" case. The two
sources never overlap — that test scans `vars:` keys nested inside
plays/tasks, this one scans top-level keys of role-and-group var
files — so they both stay green together without coordination.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import (
    iter_project_files,
    iter_project_files_with_content,
    read_text,
)
from utils.cache.yaml import load_yaml_any

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from collections.abc import Iterable

# Rule key consumed by this lint via `nocheck`-keyword suppression
# markers. A `same-or-above` placement on the var declaration line
# skips the var from the unused-var check. See
# docs/contributing/actions/testing/suppression.md.
SUPPRESS_RULE: str = "unused-var"


_TOP_LEVEL_KEY_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:")


# Variables whose absence from .yml/.j2 is expected because they are
# either consumed only by Python plugin code or set by Ansible itself
# / the runner host. Adding to this list MUST be justified inline.
_WHITELIST: frozenset[str] = frozenset(
    {
        # Connection / behavior keys consumed by Ansible itself; they
        # configure the runner and never need to surface in `{{ … }}`.
        # See https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html#connecting-to-hosts-behavioral-inventory-parameters
        "ansible_python_interpreter",
        "ansible_shell_executable",
    }
)


def _is_definition_file(path: Path, repo_root: Path) -> bool:
    """Return True for the three classes of files this lint scans."""
    rel = path.relative_to(repo_root)
    parts = rel.parts
    if (
        len(parts) >= 4
        and parts[0] == "roles"
        and parts[2] in ("vars", "defaults")
        and parts[3] == "main.yml"
    ):
        return True
    if parts and parts[0] == "group_vars":
        return path.suffix in (".yml", ".yaml")
    return False


def _iter_definition_files(repo_root: Path) -> Iterable[Path]:
    roles_root = repo_root / "roles"
    if roles_root.is_dir():
        for role_dir in sorted(roles_root.iterdir()):
            if not role_dir.is_dir():
                continue
            for sub in ("vars", "defaults"):
                f = role_dir / sub / "main.yml"
                if f.is_file():
                    yield f
    gv = repo_root / "group_vars"
    if gv.is_dir():
        gv_prefix = str(gv) + "/"
        for path_str in sorted(iter_project_files(extensions=(".yml", ".yaml"))):
            if path_str.startswith(gv_prefix):
                yield Path(path_str)


def _collect_top_level_keys(file: Path) -> list[tuple[str, int]]:
    """Return ``[(name, lineno), …]`` for every top-level mapping key
    in *file*, dropping any whose declaration line carries the
    ``unused-var`` suppression marker.

    YAML loading goes through the project's cached `load_yaml_any`;
    line numbers are best-effort via raw-text scan since `yaml.safe_load`
    discards them. The same raw-text scan feeds the suppression check,
    so a `# nocheck: unused-var` on the declaration line — or on the
    immediately preceding non-empty line — exempts the var from the
    lint without bypassing other checks.
    """
    data = load_yaml_any(file, default_if_missing={})
    if not isinstance(data, dict):
        return []

    declared: set[str] = {k for k in data if isinstance(k, str) and k.isidentifier()}
    if not declared:
        return []

    raw_lines = read_text(str(file)).splitlines()
    line_for_key: dict[str, int] = {}
    for i, line in enumerate(raw_lines, start=1):
        if line[:1].isspace():  # only true top-level (no indent)
            continue
        m = _TOP_LEVEL_KEY_RE.match(line)
        if not m:
            continue
        k = m.group(1)
        if k in declared and k not in line_for_key:
            line_for_key[k] = i

    out: list[tuple[str, int]] = []
    for k in declared:
        lineno = line_for_key.get(k, 0)
        if lineno > 0 and is_suppressed_at(
            raw_lines, lineno, SUPPRESS_RULE, mode="same-or-above"
        ):
            continue
        out.append((k, lineno))
    return sorted(out, key=lambda t: t[1])


_BLOCK_RE = re.compile(r"{{(?:(?!}}).)*?}}|{%(?:(?!%}).)*?%}", re.DOTALL)
# An identifier inside a block / expression is a USE unless it is
# immediately followed by `(` (function or macro call).
_IDENT_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\b(?!\s*\()")


def _scan_jinja_block_idents(text: str, sink: set[str]) -> None:
    for block in _BLOCK_RE.finditer(text):
        for m in _IDENT_RE.finditer(block.group(0)):
            sink.add(m.group(1))


# Ansible task-level keys that carry bare Jinja expressions (no
# `{{ … }}` wrapper). The Jinja-block scan cannot see these, so the
# parsed-structure walker has to harvest identifiers from them
# explicitly. List keyed by Ansible's documented "conditional"
# directives — extending this set is how additional false-positive
# classes get fixed (e.g. `failed_when`/`changed_when` were missing
# initially and produced false-positive "unused" reports for
# error-message constants only referenced from those keys).
_ANSIBLE_EXPR_KEYS: frozenset[str] = frozenset(
    {
        "when",
        "loop",
        "failed_when",
        "changed_when",
        "until",
    }
)


def _harvest_idents_from_value(value, sink: set[str]) -> None:
    """Pull identifiers from a value that is either a single
    expression string or a list of expression strings (Ansible accepts
    both shapes for `when:` / `failed_when:` / `changed_when:` /
    `until:`)."""
    items = value if isinstance(value, list) else [value]
    for item in items:
        if isinstance(item, str):
            for m in _IDENT_RE.finditer(item):
                sink.add(m.group(1))


def _scan_ansible_expr_idents(node, sink: set[str]) -> None:
    """Walk a parsed YAML structure and harvest identifiers from every
    Ansible expression-bearing key (`when:` / `loop:` / `with_*:` /
    `failed_when:` / `changed_when:` / `until:`).

    These keys are bare expression strings (not wrapped in `{{ … }}`),
    so the Jinja-block scan would miss them; we have to walk the
    parsed structure explicitly.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if k in _ANSIBLE_EXPR_KEYS:
                _harvest_idents_from_value(v, sink)
            if (isinstance(k, str) and k.startswith("with_")) and isinstance(v, str):
                _harvest_idents_from_value(v, sink)
            _scan_ansible_expr_idents(v, sink)
    elif isinstance(node, list):
        for item in node:
            _scan_ansible_expr_idents(item, sink)


def _scan_py_idents(text: str, sink: set[str]) -> None:
    for m in _IDENT_RE.finditer(text):
        sink.add(m.group(1))


def _build_usage_indices(repo_root: Path) -> tuple[set[str], set[str], set[str]]:
    """Single project-tree walk that builds three identifier indices.

    Routes every read through the project's cached helpers:
    * ``iter_project_files_with_content`` walks the path list once
      per process (``lru_cache(maxsize=1)`` on `_all_project_files`)
      and reads each file via the cached ``read_text``;
    * ``load_yaml_any`` parses each YAML file once per
      ``(path, mtime, size)`` signature and reuses the parsed
      structure on every later call in the same process — no
      `yaml.safe_load*` call bypasses the cache.

    Python files (plugins, filter/lookup modules, utils) are also
    scanned so that vars consumed only via ``variables.get("FOO")``
    inside an Ansible plugin count as referenced.
    """
    jinja_idents: set[str] = set()
    ansible_expr_idents: set[str] = set()
    py_idents: set[str] = set()

    for path_str, text in iter_project_files_with_content(
        extensions=(".yml", ".yaml", ".j2", ".py"),
        exclude_tests=True,
        exclude_dirs=("docs",),
    ):
        if path_str.endswith(".py"):
            _scan_py_idents(text, py_idents)
            continue
        _scan_jinja_block_idents(text, jinja_idents)
        if path_str.endswith((".yml", ".yaml")):
            data = load_yaml_any(path_str, default_if_missing=None)
            if data is not None:
                _scan_ansible_expr_idents(data, ansible_expr_idents)

    return jinja_idents, ansible_expr_idents, py_idents


class TestRoleAndGroupVarsUsed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.repo_root = PROJECT_ROOT
        (
            cls.jinja_idents,
            cls.ansible_expr_idents,
            cls.py_idents,
        ) = _build_usage_indices(cls.repo_root)

    def test_role_and_group_vars_referenced(self):
        unused: list[str] = []
        for def_file in _iter_definition_files(self.repo_root):
            rel = def_file.relative_to(self.repo_root).as_posix()
            for name, lineno in _collect_top_level_keys(def_file):
                if name in _WHITELIST:
                    continue
                if (
                    name in self.jinja_idents
                    or name in self.ansible_expr_idents
                    or name in self.py_idents
                ):
                    continue
                unused.append(f"{rel}:{lineno}: '{name}' is never referenced")

        if unused:
            self.fail(
                f"{len(unused)} role/group var(s) declared but never consumed "
                f"in any project .yml/.yaml/.j2/.py file:\n"
                + "\n".join(f"- {u}" for u in unused)
            )


if __name__ == "__main__":
    unittest.main()
