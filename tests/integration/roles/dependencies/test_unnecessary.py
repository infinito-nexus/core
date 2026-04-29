# tests/integration/test_unnecessary_role_dependencies.py
import os
import re
import glob
import yaml
import unittest
from typing import Dict, Set, List, Optional

from utils.cache.files import read_text as _read_text_cached

# ---------------- Utilities ----------------


def safe_load_yaml(path: str):
    try:
        return yaml.safe_load(_read_text_cached(path)) or {}
    except Exception:
        return {}


def read_text(path: str) -> str:
    try:
        return _read_text_cached(path)
    except Exception:
        return ""


def roles_root(project_root: str) -> str:
    return os.path.join(project_root, "roles")


def iter_role_dirs(project_root: str) -> List[str]:
    root = roles_root(project_root)
    return [d for d in glob.glob(os.path.join(root, "*")) if os.path.isdir(d)]


def role_name_from_dir(role_dir: str) -> str:
    return os.path.basename(role_dir.rstrip(os.sep))


def path_if_exists(*parts) -> Optional[str]:
    p = os.path.join(*parts)
    return p if os.path.exists(p) else None


def gather_yaml_files(base: str, patterns: List[str]) -> List[str]:
    files: List[str] = []
    for pat in patterns:
        files.extend(glob.glob(os.path.join(base, pat), recursive=True))
    return [f for f in files if os.path.isfile(f)]


# ---------------- Providers: vars & handlers ----------------


def flatten_keys(data) -> Set[str]:
    out: Set[str] = set()
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(k, str):
                out.add(k)
            out |= flatten_keys(v)
    elif isinstance(data, list):
        for item in data:
            out |= flatten_keys(item)
    return out


def collect_role_defined_vars(role_dir: str) -> Set[str]:
    """Vars a role 'provides': defaults/vars keys + set_fact keys in tasks."""
    provided: Set[str] = set()

    for rel in ("defaults/main.yml", "vars/main.yml"):
        p = path_if_exists(role_dir, rel)
        if p:
            data = safe_load_yaml(p)
            provided |= flatten_keys(data)

    # set_fact keys
    task_files = gather_yaml_files(
        os.path.join(role_dir, "tasks"), ["**/*.yml", "*.yml"]
    )
    for tf in task_files:
        data = safe_load_yaml(tf)
        if isinstance(data, list):
            for task in data:
                if (
                    isinstance(task, dict)
                    and "set_fact" in task
                    and isinstance(task["set_fact"], dict)
                ):
                    provided |= set(task["set_fact"].keys())

    noisy = {"when", "name", "vars", "tags", "register"}
    return {v for v in provided if isinstance(v, str) and v and v not in noisy}


def collect_role_handler_names(role_dir: str) -> Set[str]:
    """Handler names defined by a role (for notify detection)."""
    handler_file = path_if_exists(role_dir, "handlers/main.yml")
    if not handler_file:
        return set()
    data = safe_load_yaml(handler_file)
    names: Set[str] = set()
    if isinstance(data, list):
        for task in data:
            if isinstance(task, dict):
                nm = task.get("name")
                if isinstance(nm, str) and nm.strip():
                    names.add(nm.strip())
    return names


# ---------------- Consumers: usage scanning ----------------


def find_var_positions(text: str, varname: str) -> List[int]:
    """Return byte offsets for occurrences of varname (word-ish boundary)."""
    positions: List[int] = []
    pattern = re.compile(rf"(?<!\w){re.escape(varname)}(?!\w)")
    for m in pattern.finditer(text):
        positions.append(m.start())
    return positions


def first_var_use_offset_in_text(text: str, provided_vars: Set[str]) -> Optional[int]:
    first: Optional[int] = None
    for v in provided_vars:
        for off in find_var_positions(text, v):
            if first is None or off < first:
                first = off
    return first


def first_include_offset_for_role(text: str, producer_role: str) -> Optional[int]:
    """
    Find earliest include/import of a given role in this YAML text.
    Handles compact dict and block styles.
    """
    pattern = re.compile(
        r"(include_role|import_role)\s*:\s*\{[^}]*\bname\s*:\s*['\"]?"
        + re.escape(producer_role)
        + r"['\"]?[^}]*\}"
        r"|"
        r"(include_role|import_role)\s*:\s*\n(?:\s+[a-z_]+\s*:\s*.*\n)*\s*name\s*:\s*['\"]?"
        + re.escape(producer_role)
        + r"['\"]?",
        re.IGNORECASE,
    )
    m = pattern.search(text)
    return m.start() if m else None


def find_notify_offsets_for_handlers(text: str, handler_names: Set[str]) -> List[int]:
    """
    Heuristic: for each handler name, find occurrences where 'notify' appears within
    the preceding ~200 chars. Works for single string or list-style notify blocks.
    """
    if not handler_names:
        return []
    offsets: List[int] = []
    for h in handler_names:
        # Find occurrences of the handler name
        for m in re.finditer(re.escape(h), text):
            start = m.start()
            # Look back a bit for a 'notify' token
            back = max(0, start - 200)
            context = text[back:start]
            if re.search(r"notify\s*:", context):
                offsets.append(start)
    return sorted(offsets)


def parse_meta_dependencies(role_dir: str) -> Set[str]:
    deps: Set[str] = set()
    meta = path_if_exists(role_dir, "meta/main.yml")
    if not meta:
        return deps
    data = safe_load_yaml(meta)
    dd = data.get("dependencies")
    if isinstance(dd, list):
        for item in dd:
            if isinstance(item, str):
                deps.add(item)
            elif isinstance(item, dict) and "role" in item:
                deps.add(str(item["role"]))
            elif isinstance(item, dict) and "name" in item:
                deps.add(str(item["name"]))
    return deps


# ---------------- The Test ----------------


class TestUnnecessaryRoleDependencies(unittest.TestCase):
    """
    Flags meta dependencies that can be replaced with guarded include_role/import_role
    to avoid repeated parsing/execution.

    A dependency is considered UNNECESSARY if:
      - The consumer does not need provider vars in defaults/vars/handlers (no early-var need),
      AND
      - In tasks, any usage of provider vars or notifications to provider handlers
        occurs only after an include/import of the provider in the same file,
        OR there is no usage at all.
    """

    def setUp(self):
        # project root = two levels up from this test file
        self.project_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")
        )
        self.roles = iter_role_dirs(self.project_root)

        # Index provider data
        self.role_vars: Dict[str, Set[str]] = {}
        self.role_handlers: Dict[str, Set[str]] = {}
        for rd in self.roles:
            rn = role_name_from_dir(rd)
            self.role_vars[rn] = collect_role_defined_vars(rd)
            self.role_handlers[rn] = collect_role_handler_names(rd)

        # Map meta deps
        self.role_meta_deps: Dict[str, Set[str]] = {}
        for rd in self.roles:
            rn = role_name_from_dir(rd)
            self.role_meta_deps[rn] = parse_meta_dependencies(rd)

    def test_unnecessary_meta_dependencies(self):
        warnings: List[str] = []

        # Prepare lookup: role_dir by name
        role_dir_by_name = {role_name_from_dir(rd): rd for rd in self.roles}

        for consumer_dir in self.roles:
            consumer = role_name_from_dir(consumer_dir)
            meta_deps = self.role_meta_deps.get(consumer, set())
            if not meta_deps:
                continue

            # Load consumer files
            defaults_files = [
                p
                for p in [
                    path_if_exists(consumer_dir, "defaults/main.yml"),
                    path_if_exists(consumer_dir, "vars/main.yml"),
                    path_if_exists(consumer_dir, "handlers/main.yml"),
                ]
                if p
            ]
            defaults_texts = [(p, read_text(p)) for p in defaults_files]

            task_files = gather_yaml_files(
                os.path.join(consumer_dir, "tasks"), ["**/*.yml", "*.yml"]
            )
            task_texts = [(p, read_text(p)) for p in task_files]

            for producer in sorted(meta_deps):
                # Skip unknown producer dirs (e.g., external roles)
                pdir = role_dir_by_name.get(producer)
                if not pdir:
                    continue

                provided_vars = self.role_vars.get(producer, set())
                provider_handlers = self.role_handlers.get(producer, set())

                # --- 1) Early usage in defaults/vars/handlers? If yes -> necessary, skip.
                early_use = False
                for path, text in defaults_texts:
                    if not text:
                        continue
                    off = first_var_use_offset_in_text(text, provided_vars)
                    if off is not None:
                        early_use = True
                        break
                    # Handler notify here is unusual; we skip.

                if early_use:
                    # Necessary because consumer needs producer vars before tasks run.
                    continue

                # --- 2) Task-level analysis
                any_usage = False
                any_bad_order = False

                for path, text in task_texts:
                    if not text:
                        continue

                    include_off = first_include_offset_for_role(text, producer)
                    var_use_off = first_var_use_offset_in_text(text, provided_vars)
                    notify_offs = find_notify_offsets_for_handlers(
                        text, provider_handlers
                    )

                    if var_use_off is not None:
                        any_usage = True
                        if include_off is None or include_off > var_use_off:
                            # Uses provider vars before ensuring it's loaded in this file.
                            any_bad_order = True

                    for noff in notify_offs:
                        any_usage = True
                        if include_off is None or include_off > noff:
                            # Notifies provider handler before including provider in this file.
                            any_bad_order = True

                # Decide: unnecessary if no early use, and either no usage at all,
                # or all usages happen after an include in their respective files.
                if not any_bad_order:
                    if not any_usage:
                        reason = "no variable/handler usage detected in consumer"
                        warnings.append(
                            f"[{consumer}] meta dependency on '{producer}' appears unnecessary: {reason}."
                        )
                    else:
                        # Usage exists but guarded by include in each file
                        reason = "all usages occur after include/import in the same task file"
                        warnings.append(
                            f"[{consumer}] meta dependency on '{producer}' appears unnecessary: {reason}."
                        )

        if warnings:
            msg = (
                "Potentially unnecessary meta dependencies found.\n"
                "Suggestion: replace with guarded include_role/import_role to reduce parsing/exec overhead.\n\n"
                + "\n".join(f"- {w}" for w in warnings)
                + "\n\nHeuristics/limits:\n"
                "- We detect provider vars from defaults/vars/set_fact, and provider handler names from handlers/main.yml.\n"
                "- We check consumer defaults/vars/handlers for early-var needs (makes dependency necessary).\n"
                "- In tasks, we require include/import to appear BEFORE any var use or notify in the same file.\n"
                "- Cross-file task order is not analyzed; the test is conservative to avoid false positives."
            )
            self.fail(msg)
