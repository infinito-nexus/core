import unittest
from pathlib import Path
from typing import Any

import yaml

from utils.cache.files import iter_project_files
from utils.cache.yaml import load_yaml_all

from . import PROJECT_ROOT


# -------- YAML loader that's tolerant of Ansible-specific tags (e.g. !vault) -----
class AnsibleTolerantLoader(yaml.SafeLoader):
    pass


def _ansible_tag_passthrough(loader: yaml.Loader, tag_prefix: str, node: yaml.Node):
    # Treat unknown/Ansible custom tags as plain YAML
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None


yaml.add_multi_constructor("!", _ansible_tag_passthrough, Loader=AnsibleTolerantLoader)

# -------------------------------------------------------------------------------


Yaml = dict[str, Any] | list[Any] | Any


def _iter_yaml_files(root: Path) -> list[Path]:
    """Return all ``*.yml`` files in the repository (excluding common junk dirs)."""
    ignore_dirs = {
        ".git",
        ".venv",
        "venv",
        ".tox",
        ".idea",
        ".pytest_cache",
        "__pycache__",
    }
    root_prefix = str(root) + "/"
    files: list[Path] = []
    for path_str in iter_project_files(extensions=(".yml",)):
        if not path_str.startswith(root_prefix):
            continue
        path = Path(path_str)
        if any(part in ignore_dirs for part in path.parts):
            continue
        files.append(path)
    return files


def _safe_load_all(path: Path) -> list[Yaml]:
    """Load all YAML documents from a file, tolerating Ansible tags; return list of docs."""
    try:
        return list(load_yaml_all(str(path)))
    except Exception:
        # If a file is completely unparsable, treat as empty (so test won't crash).
        return []


def _find_blocks_with_when(
    node: Yaml, path: str = ""
) -> list[tuple[str, dict[str, Any]]]:
    """
    Recursively find mappings that represent an Ansible block with a block-level `when`.
    Returns list of (yaml_path, block_mapping).
    """
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if "block" in node and "when" in node and isinstance(node["block"], list):
            found.append((path or "/", node))
        # Recurse into all values to catch nested blocks
        for k, v in node.items():
            child_path = f"{path}/{k}" if path else f"/{k}"
            found.extend(_find_blocks_with_when(v, child_path))
    elif isinstance(node, list):
        for i, item in enumerate(node):
            child_path = f"{path}[{i}]"
            found.extend(_find_blocks_with_when(item, child_path))
    return found


def _len_if_list(x: Any) -> int:
    return len(x) if isinstance(x, list) else 0


class BlockWhenSizeTest(unittest.TestCase):
    MAX_TASKS = 3  # performance threshold

    def test_blocks_with_when_and_sections_have_max_three_tasks(self):
        root = PROJECT_ROOT
        violations: list[str] = []

        for yml in _iter_yaml_files(root):
            docs = _safe_load_all(yml)
            if not docs:
                continue

            for doc_idx, doc in enumerate(docs):
                blocks = _find_blocks_with_when(doc, path=f"{yml}:{doc_idx}")
                for yaml_path, mapping in blocks:
                    name = mapping.get("name") or "<unnamed block>"
                    when_expr = mapping.get("when")

                    # Check main block size
                    block_tasks = mapping.get("block", [])
                    block_count = _len_if_list(block_tasks)
                    if block_count > self.MAX_TASKS:
                        violations.append(
                            f"[PERFORMANCE VIOLATION] {yml} :: {name} :: section=block "
                            f":: tasks={block_count} (> {self.MAX_TASKS}) "
                            f":: when={when_expr!r} :: at {yaml_path}"
                        )

                    # Check rescue size (if present)
                    rescue_tasks = mapping.get("rescue", [])
                    rescue_count = _len_if_list(rescue_tasks)
                    if rescue_count > self.MAX_TASKS:
                        violations.append(
                            f"[PERFORMANCE VIOLATION] {yml} :: {name} :: section=rescue "
                            f":: tasks={rescue_count} (> {self.MAX_TASKS}) "
                            f":: parent-when={when_expr!r} :: at {yaml_path}/rescue"
                        )

                    # Check always size (if present)
                    always_tasks = mapping.get("always", [])
                    always_count = _len_if_list(always_tasks)
                    if always_count > self.MAX_TASKS:
                        violations.append(
                            f"[PERFORMANCE VIOLATION] {yml} :: {name} :: section=always "
                            f":: tasks={always_count} (> {self.MAX_TASKS}) "
                            f":: parent-when={when_expr!r} :: at {yaml_path}/always"
                        )

        if violations:
            self.fail(
                "Blocks with a block-level 'when' must contain at most 3 tasks per section "
                "('block', 'rescue', 'always') for performance reasons.\n"
                "Rationale:\n"
                " - A block-level 'when' does NOT prevent parsing of tasks inside the block; "
                "   all sections ('block', 'rescue', 'always') are parsed and then may be skipped at runtime, "
                "   causing parse time and module redirect overhead.\n"
                "Recommendation:\n"
                " - Keep the block structure (for rescue/always, become, vars, etc.), but place a single "
                "   `include_tasks` INSIDE the respective section and put the condition on that include "
                "   (where feasible). When the condition is false, the included file is not parsed at all.\n"
                "Example:\n"
                " - Bad (heavy tasks directly in sections):\n"
                "     - block:\n"
                "         - package: name=foo state=present\n"
                "         - template: src=a.j2 dest=/a\n"
                "       rescue:\n"
                "         - debug: msg='rollback-1'\n"
                "         - debug: msg='rollback-2'\n"
                "       always:\n"
                "         - debug: msg='cleanup-1'\n"
                "       when: feature_enabled\n\n"
                " - Good (preserve semantics, avoid parsing when skipped):\n"
                "     - block:\n"
                "         - include_tasks: heavy_setup.yml\n"
                "           when: feature_enabled | bool\n"
                "       rescue:\n"
                "         - include_tasks: rollback.yml\n"
                "           when: feature_enabled | bool  # add a guard if rollback is heavy/rare\n"
                "       always:\n"
                "         - include_tasks: cleanup.yml\n"
                "           when: feature_enabled | bool  # add a guard if cleanup is heavy/rare\n"
                "       when: feature_enabled\n\n"
                "Violations:\n" + "\n".join(violations)
            )


if __name__ == "__main__":
    unittest.main()
