"""Apply the chosen fix: rewrite meta + prepend guarded include block."""

from __future__ import annotations

import os
from typing import List

from ruamel.yaml.comments import CommentedSeq

from .yaml_io import dump_yaml_rt, load_yaml_rt


def sanitize_run_once_var(role_name: str) -> str:
    return "run_once_" + role_name.replace("-", "_")


def build_include_block_yaml(consumer_role: str, moved_deps: List[str]) -> List[dict]:
    """Guarded block prepended to tasks/01_core.yml or tasks/main.yml."""
    guard_var = sanitize_run_once_var(consumer_role)

    if len(moved_deps) == 1:
        inner_tasks: List[dict] = [
            {
                "name": f"Include dependency '{moved_deps[0]}'",
                "include_role": {"name": moved_deps[0]},
            }
        ]
    else:
        inner_tasks = [
            {
                "name": "Include dependencies",
                "include_role": {"name": "{{ item }}"},
                "loop": moved_deps,
            }
        ]
    inner_tasks.append({"set_fact": {guard_var: True}})

    return [
        {
            "name": "Load former meta dependencies once",
            "block": inner_tasks,
            "when": f"{guard_var} is not defined",
        }
    ]


def prepend_tasks(tasks_path: str, new_tasks, dry_run: bool) -> None:
    if os.path.exists(tasks_path):
        existing = load_yaml_rt(tasks_path)
        if isinstance(existing, list):
            combined = CommentedSeq()
            for item in new_tasks:
                combined.append(item)
            for item in existing:
                combined.append(item)
        elif isinstance(existing, dict):
            combined = CommentedSeq()
            for item in new_tasks:
                combined.append(item)
            combined.append(existing)
        else:
            combined = new_tasks
    else:
        os.makedirs(os.path.dirname(tasks_path), exist_ok=True)
        combined = new_tasks

    if dry_run:
        print(
            f"[DRY-RUN] Would write {tasks_path} with {len(new_tasks)} prepended task(s)."
        )
        return

    dump_yaml_rt(combined, tasks_path)
    print(f"[OK] Updated {tasks_path} (prepended {len(new_tasks)} task(s)).")


def update_meta_remove_deps(meta_path: str, remove: List[str], dry_run: bool) -> bool:
    """Drop given entries from meta.dependencies, preserving everything else."""
    if not os.path.exists(meta_path):
        return False
    doc = load_yaml_rt(meta_path)
    deps = doc.get("dependencies")
    if not isinstance(deps, list):
        return False

    keep = CommentedSeq()
    removed: List[str] = []
    for item in deps:
        name = item.get("role") or item.get("name") if isinstance(item, dict) else item
        if name in remove:
            removed.append(name)
        else:
            keep.append(item)

    if not removed:
        return False

    if keep:
        doc["dependencies"] = keep
    elif "dependencies" in doc:
        del doc["dependencies"]

    if dry_run:
        print(f"[DRY-RUN] Would rewrite {meta_path}; removed: {', '.join(removed)}")
        return True
    dump_yaml_rt(doc, meta_path)
    print(f"[OK] Rewrote {meta_path}; removed: {', '.join(removed)}")
    return True
