"""Warn about folders that grow beyond the readability/modularity limit.

This lint test scans git-tracked repository files and counts the
immediate items of each folder. Ignored files are skipped by design.
Folders with more than 12 direct items are reported as non-blocking warnings
so that large directories stay easy to scan and keep a clear module boundary.

In GitHub Actions, each offending folder emits its own ``::warning`` line.
When run locally, the test prints one shared warning header and a list of the
affected folders.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from utils.annotations.message import warning
from utils.cache.files import iter_project_files

from . import PROJECT_ROOT

MAX_ITEMS_PER_FOLDER = 12

# Flat structure folders that intentionally stay one level deep.
FLAT_STRUCTURE_WHITELIST = {
    ".github/workflows",
    "cli",
    "cli/administration/inventory/provision",
    "cli/administration/deploy/development",
    "group_vars/all",
    "plugins/filter",
    "plugins/lookup",
    "roles",
    "inventories/bundles/servers",
    "inventories/bundles/workstations",
    "tasks/groups",
    "tests/unit/plugins/filter",
    "tests/unit/roles",
    "tests/unit/plugins/lookup",
}


@dataclass(frozen=True)
class FolderFinding:
    folder: Path
    children: tuple[str, ...]

    @property
    def item_count(self) -> int:
        return len(self.children)


def _tracked_paths(root: Path) -> list[Path]:
    """Return tracked file paths.

    Tracked paths already exclude ignored files. If git is unavailable, fall
    back to a filesystem walk and apply a light safety filter.
    """
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "ls-files", "-z"],
            stderr=subprocess.STDOUT,
        )
    except Exception:
        # `iter_project_files` already prunes `.git`, `__pycache__`,
        # `.cache`, `.venv`, `node_modules`, etc.
        return [Path(p) for p in iter_project_files()]

    rel_paths = [
        rel_path
        for rel_path in output.decode("utf-8", errors="replace").split("\0")
        if rel_path
    ]
    return [root / rel_path for rel_path in rel_paths]


def _collect_folder_findings(root: Path) -> list[FolderFinding]:
    """Collect folders with more than MAX_ITEMS_PER_FOLDER direct items."""
    folder_children: dict[Path, set[str]] = defaultdict(set)

    for path in _tracked_paths(root):
        rel_parts = path.relative_to(root).parts
        if len(rel_parts) < 2:
            continue

        for depth in range(len(rel_parts) - 1):
            parent = Path(*rel_parts[: depth + 1])
            child = rel_parts[depth + 1]
            folder_children[parent].add(child)

    findings: list[FolderFinding] = []
    for folder, children in sorted(
        folder_children.items(), key=lambda item: item[0].as_posix()
    ):
        if _is_whitelisted_folder(folder):
            continue
        if len(children) > MAX_ITEMS_PER_FOLDER:
            findings.append(
                FolderFinding(folder=folder, children=tuple(sorted(children)))
            )

    return findings


def _is_whitelisted_folder(folder: Path) -> bool:
    """Return True for folders that are intentionally allowed to stay broad."""
    rel = folder.as_posix()
    if rel in FLAT_STRUCTURE_WHITELIST:
        return True
    # The first level below roles/ is intentionally flat by design.
    return len(folder.parts) == 2 and folder.parts[0] == "roles"


def _emit_ci_warning(finding: FolderFinding) -> None:
    message = (
        f"{finding.folder.as_posix()} has {finding.item_count} immediate items. "
        f"Max {MAX_ITEMS_PER_FOLDER} items are intended for readability and "
        f"modularity."
    )
    if os.environ.get("GITHUB_ACTIONS") == "true":
        warning(
            message, title="Folder item limit exceeded", file=finding.folder.as_posix()
        )


def _print_cli_summary(findings: list[FolderFinding]) -> None:
    if not findings:
        print(f"No tracked folders exceed the {MAX_ITEMS_PER_FOLDER}-item limit.")
        return

    print(
        f"\n[WARNING] Folders with more than {MAX_ITEMS_PER_FOLDER} immediate items are "
        "reported because readability and modularity work best with smaller folders.\n"
        f"Max {MAX_ITEMS_PER_FOLDER} immediate items per folder is the intended ceiling.\n"
        "Affected folders:\n"
        + "\n".join(
            f"- {finding.folder.as_posix()} ({finding.item_count} items)"
            for finding in findings
        )
    )


class TestFolderItemLimit(unittest.TestCase):
    def test_folder_item_limit_warns_only(self) -> None:
        """Warn when any tracked folder exceeds the direct item limit."""
        self.assertTrue(
            PROJECT_ROOT.is_dir(), f"Repository root not found at: {PROJECT_ROOT}"
        )

        findings = _collect_folder_findings(PROJECT_ROOT)

        for finding in findings:
            _emit_ci_warning(finding)

        if os.environ.get("GITHUB_ACTIONS") != "true":
            _print_cli_summary(findings)
        elif not findings:
            print(f"No tracked folders exceed the {MAX_ITEMS_PER_FOLDER}-item limit.")

        self.assertTrue(True)


if __name__ == "__main__":
    unittest.main()
