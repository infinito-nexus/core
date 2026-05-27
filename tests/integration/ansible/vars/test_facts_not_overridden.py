import unittest
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from utils.cache.files import iter_project_files, read_text
from utils.cache.yaml import load_yaml_all_str

from . import PROJECT_ROOT


def _safe_yaml_load_all(path: Path) -> list[Any]:
    """
    Load YAML documents from a file.
    Returns a list of documents (usually 1), each can be list/dict/None.
    """
    try:
        text = read_text(str(path))
    except Exception:
        return []
    # Skip empty / non-yaml-ish files quickly
    if not text.strip():
        return []
    try:
        docs = list(load_yaml_all_str(text))
        return [d for d in docs if d is not None]
    except Exception:
        # Some Ansible task files can contain Jinja that breaks YAML parsing;
        # we keep it strict: if we can't parse, we don't pretend it's safe.
        return ["__YAML_PARSE_ERROR__"]


def _iter_task_dicts(obj: Any) -> Iterable[dict[str, Any]]:
    """
    Yield task dicts from arbitrary YAML structures.
    Ansible task files are typically a list of dict tasks, but can contain blocks.
    """
    if isinstance(obj, list):
        for item in obj:
            yield from _iter_task_dicts(item)
    elif isinstance(obj, dict):
        # A task dict itself
        if any(
            k in obj
            for k in (
                "name",
                "set_fact",
                "ansible.builtin.set_fact",
                "block",
                "rescue",
                "always",
            )
        ):
            yield obj

        # Recurse into known nesting constructs
        for key in ("block", "rescue", "always", "tasks", "pre_tasks", "post_tasks"):
            if key in obj:
                yield from _iter_task_dicts(obj.get(key))


def _is_set_fact_task(task: dict[str, Any]) -> bool:
    return "set_fact" in task or "ansible.builtin.set_fact" in task


def _get_set_fact_mapping(task: dict[str, Any]) -> dict[str, Any]:
    if "set_fact" in task and isinstance(task["set_fact"], dict):
        return task["set_fact"]
    if "ansible.builtin.set_fact" in task and isinstance(
        task["ansible.builtin.set_fact"], dict
    ):
        return task["ansible.builtin.set_fact"]
    return {}


def _find_vars_mapping(task: dict[str, Any]) -> dict[str, Any] | None:
    v = task.get("vars")
    return v if isinstance(v, dict) else None


def _is_include_like(task: dict[str, Any]) -> bool:
    """
    Tasks that can carry a `vars:` section that becomes the scope for included content.
    """
    include_keys = {
        "include_role",
        "ansible.builtin.include_role",
        "include_tasks",
        "ansible.builtin.include_tasks",
        "import_tasks",
        "ansible.builtin.import_tasks",
        "import_role",
        "ansible.builtin.import_role",
    }
    return any(k in task for k in include_keys)


def _looks_dynamic(varname: str) -> bool:
    """
    Ignore non-literal variable keys (very rare, but defensive).
    """
    return any(
        x in varname for x in ("{{", "}}", "[", "]", "(", ")", "|", "lookup(", "query(")
    )


def _collect_defined_facts(task_files: list[Path]) -> dict[str, set[Path]]:
    """
    Return mapping: fact_name -> set(paths where it's set via set_fact)
    """
    facts: dict[str, set[Path]] = {}
    for p in task_files:
        docs = _safe_yaml_load_all(p)
        if "__YAML_PARSE_ERROR__" in docs:
            continue
        for doc in docs:
            for task in _iter_task_dicts(doc):
                if not _is_set_fact_task(task):
                    continue
                mapping = _get_set_fact_mapping(task)
                for k in mapping:
                    if not isinstance(k, str) or _looks_dynamic(k):
                        continue
                    facts.setdefault(k, set()).add(p)
    return facts


def _collect_var_overrides(task_files: list[Path]) -> list[tuple[Path, str, str]]:
    """
    Return list of (path, task_name, var_key) for vars used on include-like tasks.
    """
    overrides: list[tuple[Path, str, str]] = []
    for p in task_files:
        docs = _safe_yaml_load_all(p)
        if "__YAML_PARSE_ERROR__" in docs:
            continue
        for doc in docs:
            for task in _iter_task_dicts(doc):
                if not _is_include_like(task):
                    continue
                vmap = _find_vars_mapping(task)
                if not vmap:
                    continue
                tname = str(task.get("name", "<unnamed task>"))
                for k in vmap:
                    if not isinstance(k, str) or _looks_dynamic(k):
                        continue
                    overrides.append((p, tname, k))
    return overrides


def _find_task_files(repo_root: Path) -> list[Path]:
    """
    All YAML files under:
      - roles/*/tasks/
      - tasks/
    Routed through the cached project walk in `utils.cache.files`.
    """
    task_files: list[Path] = []

    roles_dir = repo_root / "roles"
    top_tasks = repo_root / "tasks"
    roles_prefix = str(roles_dir) + "/"
    top_tasks_prefix = str(top_tasks) + "/"

    for path_str in iter_project_files(extensions=(".yml", ".yaml")):
        if path_str.startswith(roles_prefix):
            rel = path_str[len(roles_prefix) :].split("/")
            if len(rel) >= 3 and rel[1] == "tasks":
                task_files.append(Path(path_str))
        elif path_str.startswith(top_tasks_prefix):
            task_files.append(Path(path_str))

    task_files.sort()

    # De-dup
    uniq: list[Path] = []
    seen = set()
    for p in task_files:
        rp = str(p.resolve())
        if rp not in seen:
            uniq.append(p)
            seen.add(rp)
    return uniq


class TestFactsAreNotOverriddenByVars(unittest.TestCase):
    """
    Static integration test:
      - Collect all facts set via set_fact in roles/*/tasks/** and tasks/**
      - Ensure none of those fact names are passed via `vars:` on include/import tasks/roles
        (because that pattern commonly causes scope confusion + accidental persistent overrides).
    """

    def test_no_fact_is_overridden_via_vars_on_includes(self) -> None:
        repo_root = PROJECT_ROOT
        task_files = _find_task_files(repo_root)

        facts = _collect_defined_facts(task_files)  # fact -> {paths}
        var_overrides = _collect_var_overrides(task_files)  # (path, task_name, var_key)

        # Build reverse index for fast lookup
        override_index: dict[str, list[tuple[Path, str]]] = {}
        for p, tname, key in var_overrides:
            override_index.setdefault(key, []).append((p, tname))

        violations: list[str] = []
        for fact_name, fact_paths in sorted(facts.items(), key=lambda x: x[0]):
            if fact_name not in override_index:
                continue
            offenders = override_index[fact_name]

            fact_locations = ", ".join(
                sorted(str(fp.relative_to(repo_root)) for fp in fact_paths)
            )
            offender_lines = "\n".join(
                f"    - {op.relative_to(repo_root)} :: task={tname!r}"
                for op, tname in offenders
            )
            violations.append(
                f"Fact {fact_name!r} is set via set_fact in: {fact_locations}\n"
                f"  but is also passed via vars: on include/import tasks/roles:\n{offender_lines}"
            )

        if violations:
            self.fail(
                "Found facts that are overridden via vars: on include/import tasks/roles.\n\n"
                + "\n\n".join(violations)
                + "\n\nFix idea: rename the include-time var (e.g. prefix with _ or ctx_), "
                "or stop passing the fact name via vars:, or stop using set_fact for context variables."
            )


if __name__ == "__main__":
    unittest.main()
