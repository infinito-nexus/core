import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_all_str

from . import PROJECT_ROOT

THRESHOLD = 3  # fail if the same when-condition occurs on more than this many tasks


def _normalize_when(value: Any) -> str:
    """
    Normalize Ansible 'when' to a comparable string:
    - If it's a list, join with ' && ' preserving order (order matters in Ansible).
    - If it's a scalar, strip leading/trailing whitespace.
    - Represent everything as a single-line string for stable comparison.
    """
    if value is None:
        return ""
    if isinstance(value, list):
        parts = []
        for v in value:
            s = "" if v is None else str(v).strip()
            # collapse internal whitespace runs to a single space for stability
            s = " ".join(s.split())
            parts.append(s)
        return " && ".join(parts)
    # scalar (str, int, bool, jinja template, etc.)
    s = str(value).strip()
    return " ".join(s.split())


def _iter_tasks(node: Any) -> Iterable[dict[str, Any]]:
    """
    Yield task-like dicts (those which may contain 'when') from arbitrary YAML structures.
    Handles:
      - Top-level lists of tasks
      - Dicts that contain keys like 'block', 'rescue', 'always' (Ansible blocks)
      - Nested lists/dicts recursively
    We only yield a dict once as a "task" (the one that has a 'when' or looks like a task).
    """
    if isinstance(node, list):
        for item in node:
            yield from _iter_tasks(item)
    elif isinstance(node, dict):
        # If this dict itself looks like a task (has module keys or 'when'/'name'),
        # yield it, but also traverse nested blocks.
        is_task_like = any(
            k in node
            for k in (
                "when",
                "name",
                "block",
                "rescue",
                "always",
                "include_tasks",
                "import_tasks",
                "ansible.builtin.include_tasks",
                "ansible.builtin.import_tasks",
            )
        )
        if is_task_like:
            yield node

        # Recurse into Ansible block sections if present
        for section in ("block", "rescue", "always"):
            if section in node and isinstance(node[section], list):
                for item in node[section]:
                    yield from _iter_tasks(item)
        # Also traverse other nested structures conservatively
        for k, v in node.items():
            if k not in ("block", "rescue", "always") and isinstance(v, (list, dict)):
                yield from _iter_tasks(v)


def _load_yaml_documents(path: Path) -> list[Any]:
    """
    Load all YAML documents from a file. Best-effort parsing:
    - If YAML fails due to Jinja syntax, we still raise, because a broken file
      should be fixed in the repo.
    """
    text = read_text(str(path))
    return list(load_yaml_all_str(text))  # may return [None] if empty


def _collect_when_counts(yaml_docs: list[Any]) -> dict[str, list[tuple[str, str]]]:
    """
    Return a mapping: normalized_when -> list of (task_name, hint_location)
    where each entry corresponds to a task that uses that 'when'.
    """
    counts: dict[str, list[tuple[str, str]]] = {}
    for doc in yaml_docs:
        for task in _iter_tasks(doc):
            if "when" not in task:
                continue
            normalized = _normalize_when(task.get("when"))
            if not normalized:
                continue
            task_name = str(task.get("name") or "<unnamed task>")
            # Provide a minimal hint for where this came from (e.g., module/inclusion used)
            hint = None
            for key in (
                "include_tasks",
                "import_tasks",
                "ansible.builtin.include_tasks",
                "ansible.builtin.import_tasks",
            ):
                if key in task:
                    hint = f"{key}: {task[key]}"
                    break
            hint_loc = hint or "task"
            counts.setdefault(normalized, []).append((task_name, hint_loc))
    return counts


class WhenConditionDuplicationTest(unittest.TestCase):
    """
    Integration test that ensures we don't repeat the same 'when' condition
    on too many tasks in a single tasks file.

    Rationale:
      Repeating identical 'when' across many tasks forces Ansible to evaluate
      the same condition over and over, which is bad for performance. Prefer
      factoring those tasks into a dedicated file and use `include_tasks`
      (or a block with a single 'when') to evaluate once.
    """

    def test_excessive_repeated_when_in_tasks_files(self):
        repo_root = PROJECT_ROOT
        tasks_globs = [
            "**/tasks/**/*.yml",
            "**/tasks/**/*.yaml",
        ]

        violations: list[str] = []

        for pattern in tasks_globs:
            for path in repo_root.glob(pattern):
                # Only scan files that are inside the project workspace
                if not path.is_file():
                    continue

                try:
                    docs = _load_yaml_documents(path)
                except Exception as exc:
                    self.fail(f"Failed to parse YAML file: {path}\n{exc}")

                counts = _collect_when_counts(docs)
                for normalized_when, occurrences in counts.items():
                    if len(occurrences) > THRESHOLD:
                        # Build a helpful error message showing a few sample tasks with this condition
                        sample = "\n".join(
                            f"    - {tname} ({hint})" for tname, hint in occurrences[:5]
                        )
                        violations.append(
                            f"{path} uses the same 'when' condition more than {THRESHOLD} times "
                            f"({len(occurrences)} occurrences):\n"
                            f"  WHEN: {normalized_when}\n"
                            f"  Sample tasks:\n{sample}\n"
                            f"Suggestion: Group these tasks into a separate file and call it with "
                            f"`include_tasks`, or use a single `block` guarded by this 'when' to avoid "
                            f"re-evaluating the condition repeatedly."
                        )

        if violations:
            self.fail(
                "Excessive duplicate 'when' conditions detected (hurts performance):\n\n"
                + "\n\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
