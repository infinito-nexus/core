import re
import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import yaml

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_all
from utils.roles.mapping import ROLE_FILE_HANDLERS_MAIN

# ---------- YAML helpers ----------


def load_yaml_documents(path: str) -> list[Any]:
    """
    Load one or more YAML documents from a file and return them as a list.
    Raises AssertionError with a helpful message on parse errors.
    """
    try:
        docs = list(load_yaml_all(path))
    except yaml.YAMLError as e:
        raise AssertionError(f"YAML parsing error in {path}: {e}") from e
    return [d for d in docs if d is not None]


def _iter_task_like_entries(node: Any) -> Iterable[dict[str, Any]]:
    """
    Recursively yield task/handler-like dict entries from a YAML node.
    Handles top-level lists and dict-wrapped lists, and also drills into
    Ansible blocks ('block', 'rescue', 'always') or any list of dicts.
    """
    if isinstance(node, list):
        for item in node:
            yield from _iter_task_like_entries(item)
    elif isinstance(node, dict):
        # Consider any dict as a potential task/handler entry.
        yield node
        # Recurse into list-of-dicts values (blocks, etc.)
        for v in node.values():
            if isinstance(v, list) and any(isinstance(x, dict) for x in v):
                yield from _iter_task_like_entries(v)


def iter_task_like_entries(docs: list[Any]) -> Iterable[dict[str, Any]]:
    for doc in docs:
        yield from _iter_task_like_entries(doc)


def as_str_list(val: Any) -> list[str]:
    """Normalize a YAML value (string or list) into a list of strings."""
    if val is None:
        return []
    if isinstance(val, str):
        return [val]
    if isinstance(val, list):
        return [str(v) for v in val]
    return [str(val)]


# ---------- Notify extraction helpers ----------

# Extract quoted literals inside a string (e.g. from Jinja conditionals)
_QUOTED_RE = re.compile(r"""(['"])(.+?)\1""")


def _jinja_mixed_to_regex(value: str) -> re.Pattern | None:
    """
    Turn a string that mixes plain text with Jinja placeholders into a ^...$ regex.
    Example: 'Import {{ folder }} LDIF files' -> r'^Import .+ LDIF files$'
    Returns None if there is no Jinja placeholder.
    """
    s = value.strip()
    if "{{" not in s or "}}" not in s:
        return None
    parts = re.split(r"(\{\{.*?\}\})", s)
    regex_str = (
        "^"
        + "".join(
            (".+" if p.startswith("{{") and p.endswith("}}") else re.escape(p))
            for p in parts
        )
        + "$"
    )
    return re.compile(regex_str)


def _expand_dynamic_notify(value: str) -> list[str]:
    """
    If 'value' is a Jinja expression like:
        "{{ 'reload system daemon' if cond else 'refresh systemctl service' }}"
    then extract all quoted literals as potential targets.
    Always include the raw value too (in case it is already a plain name).
    """
    results = []
    s = value.strip()
    if s:
        results.append(s)
    if "{{" in s and "}}" in s:
        for m in _QUOTED_RE.finditer(s):
            literal = m.group(2).strip()
            if literal:
                results.append(literal)
    return results


# ---------- Extraction from handlers/tasks ----------


_IMPORT_TASKS_KEYS = ("import_tasks", "ansible.builtin.import_tasks")


def _resolve_handler_import_target(entry: dict, handler_file: str) -> str | None:
    for key in _IMPORT_TASKS_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            ref = value.strip()
            return str((Path(handler_file).parent / ref).resolve())
        if isinstance(value, dict):
            ref = value.get("file")
            if isinstance(ref, str) and ref.strip():
                return str((Path(handler_file).parent / ref.strip()).resolve())
    return None


def collect_handler_groups(handler_file: str) -> list[set[str]]:
    """
    Build groups of acceptable targets for each handler task from a handlers file.
    For each handler, collect its 'name' and all 'listen' aliases.
    A handler is considered covered if ANY alias in its group is notified.

    Follows ``import_tasks`` references to sibling handler files so a role
    can split its handlers by mode (e.g. ``compose.yml`` / ``swarm.yml``)
    without breaking the notifier check.
    """
    groups: list[set[str]] = []
    docs = load_yaml_documents(handler_file)

    for entry in iter_task_like_entries(docs):
        import_target = _resolve_handler_import_target(entry, handler_file)
        if import_target and Path(import_target).is_file():
            groups.extend(collect_handler_groups(import_target))
            continue

        names: set[str] = set()

        if isinstance(entry.get("name"), str):
            nm = entry["name"].strip()
            if nm:
                names.add(nm)

        if "listen" in entry:
            for raw_item in as_str_list(entry["listen"]):
                item = raw_item.strip()
                if item:
                    names.add(item)

        if names:
            groups.append(names)

    return groups


def collect_notify_calls_from_tasks(
    task_file: str,
) -> tuple[set[str], list[re.Pattern]]:
    """
    From a task file, collect all notification targets via:
      - 'notify:' (string or list), including dynamic Jinja expressions with literals,
      - any occurrence of 'package_notify:' (string or list), anywhere in the task dict.
    Also traverses tasks nested inside 'block', 'rescue', 'always', etc.

    Returns:
      (exact_names, regex_patterns)
    """
    notified_exact: set[str] = set()
    notified_patterns: list[re.Pattern] = []
    docs = load_yaml_documents(task_file)

    for entry in iter_task_like_entries(docs):
        # Standard notify:
        if "notify" in entry:
            for item in as_str_list(entry["notify"]):
                item_str = item.strip()

                # Case 1: whole string is just a Jinja expression -> ignore
                if item_str.startswith("{{") and item_str.endswith("}}"):
                    continue

                has_jinja = "{{" in item_str and "}}" in item_str

                # Case 2: expand quoted literals inside Jinja expressions (as exacts)
                if has_jinja:
                    # Only take the quoted literals; do NOT add the raw mixed string as exact.
                    for m in _QUOTED_RE.finditer(item_str):
                        lit = m.group(2).strip()
                        if lit:
                            notified_exact.add(lit)
                else:
                    # No Jinja -> the whole string is an exact name.
                    notified_exact.add(item_str)

                # Case 3: mixed string with Jinja placeholder -> treat as regex
                rx = _jinja_mixed_to_regex(item_str)
                if rx is not None:
                    notified_patterns.append(rx)

        # package_notify and nested notify anywhere in the task tree
        # (top-level or nested under vars/role_templates/etc.)
        def walk_for_nested_notify(node: Any):
            if isinstance(node, dict):
                for k, v in node.items():
                    if k in ("package_notify", "notify"):
                        for item in as_str_list(v):
                            item_str = item.strip()

                            # Ignore pure Jinja
                            if item_str.startswith("{{") and item_str.endswith("}}"):
                                continue

                            has_jinja = "{{" in item_str and "}}" in item_str

                            if has_jinja:
                                # Only quoted literals as exacts
                                for m in _QUOTED_RE.finditer(item_str):
                                    lit = m.group(2).strip()
                                    if lit:
                                        notified_exact.add(lit)
                            else:
                                notified_exact.add(item_str)

                            # mixed -> regex
                            rx = _jinja_mixed_to_regex(item_str)
                            if rx is not None:
                                notified_patterns.append(rx)
                    else:
                        walk_for_nested_notify(v)
            elif isinstance(node, list):
                for v in node:
                    walk_for_nested_notify(v)

        walk_for_nested_notify(entry)

    return notified_exact, notified_patterns


# ---------- Test case ----------


class TestHandlersInvoked(unittest.TestCase):
    """
    Ensures:
      (A) Every handler defined in roles/*/handlers/*.yml(.yaml) is referenced at least once
          via tasks' 'notify:' or any 'package_notify:' (exact or regex match from Jinja-mixed strings).
      (B) Every notified target in tasks points to an existing handler alias (name or listen).
    """

    def setUp(self):
        from . import PROJECT_ROOT

        self.roles_dir = str(PROJECT_ROOT / "roles")
        roles_prefix = self.roles_dir + "/"

        # Handlers: only main.yml/main.yaml define handlers.
        # Other files under handlers/ are typically include_tasks/import_tasks
        # and contain regular tasks, not handler definitions.
        handler_suffixes = (f"/{ROLE_FILE_HANDLERS_MAIN}", "/handlers/main.yaml")
        self.handler_files = [
            p
            for p in iter_project_files(extensions=(".yml", ".yaml"))
            if p.startswith(roles_prefix) and p.endswith(handler_suffixes)
        ]

        # Tasks: recurse under tasks for both .yml and .yaml
        def _is_role_tasks_file(p: str) -> bool:
            if not p.startswith(roles_prefix):
                return False
            parts = p[len(roles_prefix) :].split("/")
            return len(parts) >= 3 and parts[1] == "tasks"

        self.task_files = [
            p
            for p in iter_project_files(extensions=(".yml", ".yaml"))
            if _is_role_tasks_file(p)
        ]

    def test_all_handlers_have_a_notifier_and_all_notifies_have_a_handler(self):
        # 1) Collect handler groups (name + listen) for each handler task
        handler_groups: list[set[str]] = []
        for hf in self.handler_files:
            handler_groups.extend(collect_handler_groups(hf))

        # Flatten all handler aliases for reverse checks
        all_aliases: set[str] = (
            set().union(*handler_groups) if handler_groups else set()
        )

        # 2) Collect all notified targets (notify + package_notify) from tasks
        notified_exact: set[str] = set()
        notified_patterns: list[re.Pattern] = []
        for tf in self.task_files:
            ex, pats = collect_notify_calls_from_tasks(tf)
            notified_exact |= ex
            notified_patterns.extend(pats)

        def group_is_covered(grp: set[str]) -> bool:
            # exact hit?
            if grp & notified_exact:
                return True
            # regex hit?
            for alias in grp:
                for rx in notified_patterns:
                    if rx.match(alias):
                        return True
            return False

        # 3A) Every handler group is covered if any alias is notified (exact or regex)
        missing_groups: list[set[str]] = [
            grp for grp in handler_groups if not group_is_covered(grp)
        ]

        if missing_groups:
            representatives: list[str] = []
            representatives.extend(sorted(grp)[0] for grp in missing_groups)
            representatives = sorted(set(representatives))

            msg = [
                "The following handlers are defined but never notified (via 'notify:' or 'package_notify:'):",
                *[f"  - {m}" for m in representatives],
                "",
                "Notes:",
                "  • A handler is considered covered if *any* of its {name + listen} aliases is notified.",
                "  • We support dynamic Jinja notify expressions by extracting quoted literals",
                "    and by interpreting mixed strings with Jinja placeholders as wildcard regex.",
                "  • Ensure 'notify:' uses the exact handler name, one of its 'listen' aliases,",
                "    or a compatible wildcard string that matches the handler via regex.",
                "  • If you trigger builds via roles/vars, set 'package_notify:' to the handler name.",
            ]
            self.fail("\n".join(msg))

        # 3B) Reverse validation:
        #     Every notified target must resolve to an existing handler alias.
        #     - Exact notified strings must match an alias exactly.
        #     - Jinja-mixed strings (patterns) must match at least one alias via regex.
        missing_exacts = sorted([s for s in notified_exact if s not in all_aliases])

        orphan_patterns = sorted(
            {
                rx.pattern
                for rx in notified_patterns
                if not any(rx.match(alias) for alias in all_aliases)
            }
        )

        if missing_exacts or orphan_patterns:
            msg = ["Some notify targets do not map to any existing handler:"]
            if missing_exacts:
                msg.append("  • Missing exact handler aliases:")
                msg.extend([f"    - {s}" for s in missing_exacts])
            if orphan_patterns:
                msg.append(
                    "  • Pattern notifications with no matching handler alias (regex):"
                )
                msg.extend([f"    - {pat}" for pat in orphan_patterns])
            msg += [
                "",
                "Hints:",
                "  - Make sure a handler with matching 'name' or 'listen' exists.",
                "  - Pure Jinja expressions like '{{ some_var }}' are ignored in this check.",
                "  - Mixed strings like 'Import {{ folder }} LDIF files' are treated as regex (e.g., '^Import .+ LDIF files$').",
                "  - Consider adding a 'listen:' alias to the handler if you want to keep a flexible notify pattern.",
            ]
            self.fail("\n".join(msg))


if __name__ == "__main__":
    unittest.main()
