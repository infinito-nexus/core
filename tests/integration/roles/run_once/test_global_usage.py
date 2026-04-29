#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Ultra-fast + YAML-strict integration test (single pass, per-suffix validation)

What it enforces:
- For every occurrence of run_once_<suffix> in any VALID YAML file in the repo:
  * If <suffix> matches a role (roles/<role>/tasks/main.yml; suffix = role.replace('-', '_')):
      - That exact suffix must be defined EITHER
          A) globally via any `set_fact:` assigning `run_once_<suffix>: ...`, OR
          B) inside that role's tasks:
               - include_tasks|import_tasks:  OR
               - set_fact: { run_once_<suffix>: ... }
  * If <suffix> does NOT match any role (an unknown suffix):
      - It MUST be defined globally via `set_fact` somewhere in a valid YAML file.
        Otherwise: FAIL (this covers cases like `run_once_1234` in a when:).

Implementation details:
- Only VALID YAML files are scanned (PyYAML parse). Invalid YAML files are ignored.
- Unknown YAML tags (e.g. !vault) are tolerated and treated as plain values.
- Single filesystem walk, regexes compiled once, and per-role detection by path prefix.
"""

import os
import re
import unittest

from utils.cache.files import iter_project_files, read_text

try:
    import yaml  # PyYAML
except Exception:
    yaml = None

# ---------- Regexes (compiled once) ----------
# Any usage like "run_once_<suffix>"
RUN_ONCE_USAGE_RE = re.compile(r"\brun_once_([A-Za-z0-9_]+)\b")

# Task files that "define" a run-once flag for a role
RUN_ONCE_TASK_FILES = ("utils/once/flag.yml",)


def project_root():
    return os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
    )


def roles_root(root: str) -> str:
    return os.path.join(root, "roles")


def walk_yaml_files(root: str):
    """Yield absolute paths to *.yml files from the cached project walker."""
    yield from iter_project_files(extensions=(".yml",))


def read_text_safe(path: str):
    try:
        return read_text(path)
    except (OSError, UnicodeDecodeError):
        return None


# ---------- YAML loader that tolerates unknown tags (!vault etc.) ----------
class TolerantLoader(yaml.SafeLoader):  # type: ignore
    pass


def _unknown_tag_constructor(loader, tag_suffix, node):
    # Represent unknown tagged nodes as plain structures so parsing doesn't fail
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


if yaml is not None:
    TolerantLoader.add_multi_constructor("!", _unknown_tag_constructor)


def parse_yaml_documents(text: str):
    """Parse YAML into a list of documents; return None if parsing fails."""
    if yaml is None:
        return None
    try:
        return list(yaml.load_all(text, Loader=TolerantLoader))
    except Exception:
        return None


def iter_scalars(obj):
    """Yield all scalar strings (including mapping keys) from a loaded YAML object."""
    if obj is None:
        return
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, (int, float, bool)):
        return
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_scalars(item)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                yield k
            yield from iter_scalars(v)


def collect_set_fact_suffixes(obj, out_suffixes: set[str]):
    """
    Collect suffixes from structures like:
      - set_fact:
          run_once_<suffix>: <any>
    """
    if obj is None:
        return
    if isinstance(obj, list):
        for item in obj:
            collect_set_fact_suffixes(item, out_suffixes)
    elif isinstance(obj, dict):
        sf = obj.get("set_fact") or obj.get("ansible.builtin.set_fact")
        if isinstance(sf, dict):
            for k in sf.keys():
                if isinstance(k, str):
                    m = RUN_ONCE_USAGE_RE.fullmatch(k.strip())
                    if m:
                        out_suffixes.add(m.group(1))
        for v in obj.values():
            collect_set_fact_suffixes(v, out_suffixes)


def file_role_by_prefix(path: str, role_tasks_roots: dict[str, str]) -> str | None:
    """Return role name if path is under roles/<role>/tasks/**, else None."""
    for role, base in role_tasks_roots.items():
        if path.startswith(base):
            return role
    return None


def role_defines_suffix_in_doc(doc, role_suffix: str) -> bool:
    """
    Return True if this YAML doc (already parsed) defines run-once for the given role suffix via:
      A) include/import utils/once/flag.yml or utils/once/flag.yml (string or mapping style), OR
      B) set_fact: { run_once_<role_suffix>: ... }
    """
    if doc is None:
        return False
    queue = [doc]
    target_var = f"run_once_{role_suffix}"
    while queue:
        node = queue.pop()
        if isinstance(node, dict):
            # A) include/import utils/once/flag.yml or utils/once/flag.yml
            for key in ("include_tasks", "import_tasks"):
                if key in node:
                    val = node[key]
                    if isinstance(val, str) and any(
                        p in val for p in RUN_ONCE_TASK_FILES
                    ):
                        return True
                    if isinstance(val, dict):
                        for subval in val.values():
                            if isinstance(subval, str) and any(
                                p in subval for p in RUN_ONCE_TASK_FILES
                            ):
                                return True
            # B) set_fact exact var
            sf = node.get("set_fact") or node.get("ansible.builtin.set_fact")
            if isinstance(sf, dict) and target_var in sf:
                return True
            # Recurse
            for v in node.values():
                queue.append(v)
        elif isinstance(node, list):
            queue.extend(node)
    return False


class RunOnceGlobalUsageFastTest(unittest.TestCase):
    def test_run_once_used_anywhere_requires_exact_definition(self):
        root = project_root()
        rroot = roles_root(root)

        # Discover roles and their suffixes
        roles: list[str] = []
        suffix_for_role: dict[str, str] = {}
        role_tasks_roots: dict[str, str] = {}
        known_suffixes: set[str] = set()

        if os.path.isdir(rroot):
            for entry in os.listdir(rroot):
                main_yml = os.path.join(rroot, entry, "tasks", "main.yml")
                if os.path.isfile(main_yml):
                    roles.append(entry)
                    suffix = entry.replace("-", "_")
                    suffix_for_role[entry] = suffix
                    known_suffixes.add(suffix)
                    role_tasks_roots[entry] = (
                        os.path.join(rroot, entry, "tasks") + os.sep
                    )

        # Collections built in one pass
        used_suffixes: set[str] = set()  # all suffixes used anywhere (valid YAML only)
        global_defined_suffixes: set[str] = (
            set()
        )  # suffixes defined via global set_fact
        role_defined_suffixes: dict[str, set[str]] = {
            role: set() for role in roles
        }  # per-role defined suffixes

        # Single pass over all valid YAML files
        for yml in walk_yaml_files(root):
            text = read_text_safe(yml)
            if not text:
                continue
            # Quick prefilter to avoid parsing a ton of irrelevant YAML
            if not any(
                tok in text
                for tok in (
                    "run_once_",
                    "set_fact",
                    "include_tasks",
                    "import_tasks",
                    *RUN_ONCE_TASK_FILES,
                )
            ):
                continue

            docs = parse_yaml_documents(text)
            if docs is None:
                # Invalid YAML -> skip entirely (by requirement)
                continue
            if not docs:
                docs = [None]

            # 1) USAGE: collect suffixes from all scalar strings
            for doc in docs:
                for s in iter_scalars(doc):
                    for m in RUN_ONCE_USAGE_RE.finditer(s):
                        used_suffixes.add(m.group(1))

            # 2) GLOBAL DEFINITIONS: any set_fact assigning run_once_<suffix>
            for doc in docs:
                collect_set_fact_suffixes(doc, global_defined_suffixes)

            # 3) PER-ROLE DEFINITIONS
            role = file_role_by_prefix(yml, role_tasks_roots)
            if role:
                role_suffix = suffix_for_role[role]
                # utils/once/flag.yml inside role tasks defines that role's own suffix
                # OR a direct set_fact with exact run_once_<role_suffix>
                for doc in docs:
                    if role_defines_suffix_in_doc(doc, role_suffix):
                        role_defined_suffixes[role].add(role_suffix)
                        break  # no need to re-check other docs in this file

        # Build offenders:
        offenders: list[tuple[str, str, str]] = []

        # A) Unknown suffixes used (no corresponding role) must be globally defined
        for suffix in sorted(used_suffixes):
            if suffix not in known_suffixes and suffix not in global_defined_suffixes:
                offenders.append(
                    (
                        "<no-role>",
                        f"run_once_{suffix}",
                        "<global usage without global set_fact>",
                    )
                )

        # B) Known role suffixes used must be defined either globally or in that exact role
        for role in sorted(roles):
            suffix = suffix_for_role[role]
            if suffix in used_suffixes:
                if (suffix not in global_defined_suffixes) and (
                    suffix not in role_defined_suffixes[role]
                ):
                    offenders.append(
                        (role, f"run_once_{suffix}", os.path.join(rroot, role, "tasks"))
                    )

        if offenders:
            lines = [
                "Some run_once_<suffix> usages in valid YAML files are missing exact definitions.",
                "Rules:",
                "  • Unknown suffixes must be defined globally via set_fact.",
                "  • Known role suffixes must be defined globally OR in that role (include/import utils/once/flag.yml or set_fact).",
                "",
                "Offenders:",
            ]
            for role, var, where in offenders:
                lines.append(f"  - role: {role} | variable: {var} | searched: {where}")
            self.fail("\n".join(lines))


if __name__ == "__main__":
    unittest.main()
