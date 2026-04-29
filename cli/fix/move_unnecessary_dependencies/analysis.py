"""Static analysis helpers: provider vars/handlers + consumer scan."""

from __future__ import annotations

import os
import re
from typing import List, Optional, Set

from .yaml_io import (
    gather_yaml_files,
    load_yaml_rt,
    path_if_exists,
    read_text,
)


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
            provided |= flatten_keys(load_yaml_rt(p))

    task_files = gather_yaml_files(
        os.path.join(role_dir, "tasks"), ["**/*.yml", "*.yml"]
    )
    for tf in task_files:
        data = load_yaml_rt(tf)
        if not isinstance(data, list):
            continue
        for task in data:
            if isinstance(task, dict) and isinstance(task.get("set_fact"), dict):
                provided |= set(task["set_fact"].keys())

    noisy = {"when", "name", "vars", "tags", "register"}
    return {v for v in provided if isinstance(v, str) and v and v not in noisy}


def collect_role_handler_names(role_dir: str) -> Set[str]:
    handler_file = path_if_exists(role_dir, "handlers/main.yml")
    if not handler_file:
        return set()
    data = load_yaml_rt(handler_file)
    names: Set[str] = set()
    if isinstance(data, list):
        for task in data:
            if isinstance(task, dict):
                nm = task.get("name")
                if isinstance(nm, str) and nm.strip():
                    names.add(nm.strip())
    return names


def find_var_positions(text: str, varname: str) -> List[int]:
    if not varname:
        return []
    pattern = re.compile(rf"(?<!\w){re.escape(varname)}(?!\w)")
    return [m.start() for m in pattern.finditer(text)]


def first_var_use_offset_in_text(text: str, provided_vars: Set[str]) -> Optional[int]:
    first: Optional[int] = None
    for v in provided_vars:
        for off in find_var_positions(text, v):
            if first is None or off < first:
                first = off
    return first


def first_include_offset_for_role(text: str, producer_role: str) -> Optional[int]:
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
    """For each handler name, return offsets that follow a `notify:` within ~200 chars."""
    if not handler_names:
        return []
    offsets: List[int] = []
    for h in handler_names:
        for m in re.finditer(re.escape(h), text):
            start = m.start()
            context = text[max(0, start - 200) : start]
            if re.search(r"notify\s*:", context):
                offsets.append(start)
    return sorted(offsets)


def parse_meta_dependencies(role_dir: str) -> List[str]:
    meta = path_if_exists(role_dir, "meta/main.yml")
    if not meta:
        return []
    data = load_yaml_rt(meta)
    raw = data.get("dependencies")
    deps: List[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                deps.append(item)
            elif isinstance(item, dict):
                role = item.get("role") or item.get("name")
                if role is not None:
                    deps.append(str(role))
    return deps


def dependency_is_unnecessary(
    consumer_dir: str,
    consumer_name: str,
    producer_name: str,
    provider_vars: Set[str],
    provider_handlers: Set[str],
) -> bool:
    """True iff the consumer can safely move the meta dep to a guarded include."""
    early_files = [
        p
        for p in (
            path_if_exists(consumer_dir, "defaults/main.yml"),
            path_if_exists(consumer_dir, "vars/main.yml"),
            path_if_exists(consumer_dir, "handlers/main.yml"),
        )
        if p
    ]
    for p in early_files:
        if first_var_use_offset_in_text(read_text(p), provider_vars) is not None:
            return False

    task_files = gather_yaml_files(
        os.path.join(consumer_dir, "tasks"), ["**/*.yml", "*.yml"]
    )
    for p in task_files:
        text = read_text(p)
        if not text:
            continue
        include_off = first_include_offset_for_role(text, producer_name)
        var_use_off = first_var_use_offset_in_text(text, provider_vars)
        notify_offs = find_notify_offsets_for_handlers(text, provider_handlers)

        if var_use_off is not None and (
            include_off is None or include_off > var_use_off
        ):
            return False
        for noff in notify_offs:
            if include_off is None or include_off > noff:
                return False
    return True
