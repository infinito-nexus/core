"""Every ``{{ role_path }}/…`` and ``{{ playbook_dir }}/…`` path must exist."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

PATH_VARIABLE = re.compile(r"\{\{\s*(role_path|playbook_dir)\s*\}\}(/[^\s\"'{}]+)")
NOCHECK = "nocheck: role-path-target"
EXTENSIONS = (".yml", ".yaml", ".j2")
ROOT_PLAYBOOK_TREES = ("roles", "group_vars", "host_vars", "tasks")


def _base(variable: str, rel_parts: list[str]) -> Path | None:
    """Return the directory a path variable stands for in one file.

    Args:
        variable: ``role_path`` or ``playbook_dir``.
        rel_parts: the file's path below the project root, split on ``/``.

    Returns:
        The role directory for ``role_path`` (None outside ``roles/<role>/``);
        for ``playbook_dir`` the project root when the file belongs to the
        root playbook's tree, else the directory of the playbook file itself.
    """
    if variable == "playbook_dir":
        if len(rel_parts) == 1 or rel_parts[0] in ROOT_PLAYBOOK_TREES:
            return PROJECT_ROOT
        return PROJECT_ROOT.joinpath(*rel_parts[:-1])
    if len(rel_parts) > 2 and rel_parts[0] == "roles":
        return PROJECT_ROOT / rel_parts[0] / rel_parts[1]
    return None


def unresolved_targets() -> list[str]:
    """List every static path-variable target that names no existing file.

    Returns:
        One ``<file>:<line>: <variable><path>`` entry per missing target.
    """
    findings: list[str] = []
    for path_str in sorted(iter_project_files(extensions=EXTENSIONS)):
        rel_parts = Path(path_str).relative_to(PROJECT_ROOT).parts
        rel = "/".join(rel_parts)
        for lineno, line in enumerate(read_text(path_str).splitlines(), start=1):
            if NOCHECK in line:
                continue
            for match in PATH_VARIABLE.finditer(line):
                rest = line[match.end() :].lstrip()
                if rest.startswith(("{{", "~")):
                    continue
                base = _base(match.group(1), list(rel_parts))
                if base is None:
                    continue
                if not (base / match.group(2).lstrip("/")).exists():
                    findings.append(f"{rel}:{lineno}: {match.group(0)}")
    return findings


class TestRolePathTargetsResolve(unittest.TestCase):
    def test_every_role_path_and_playbook_dir_target_exists(self) -> None:
        findings = unresolved_targets()
        self.assertFalse(
            findings,
            f"{len(findings)} path(s) built from role_path or playbook_dir "
            "name no existing file; the task that reads them fails only at "
            "deploy time. Point each at the file's current location, or mark "
            f"a deliberately caller-relative line with '# {NOCHECK} <reason>':\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
