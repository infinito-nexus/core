"""Lint guard: ``role_path`` MUST NOT appear inside ``shell``/``command``
task bodies.

Background
==========
``role_path`` expands to the CONTROLLER's checkout path. A ``shell:`` or
``command:`` string is executed on the task's target host (which under swarm
is a delegated node without the checkout), so any ``{{ role_path }}/files/x``
reference breaks with 'No such file or directory' the moment the task is
delegated. Compliant forms::

    ansible.builtin.script:
      cmd: my_script.sh                       # module copies the file to the target

    ansible.builtin.shell:
      cmd: container exec -i {{ CID }} sh
      stdin: "{{ lookup('file', 'my_script.sh') }}"   # read on the controller

``lookup(...)``/``query(...)`` expressions evaluate on the controller and may
reference ``role_path`` freely; ``ansible.builtin.script`` is likewise exempt
because the module resolves and copies the file itself.

Detection
=========
Scans every ``.yml``/``.yaml`` under ``roles/`` and ``tasks/``. A task block
whose action is ``shell``/``command`` (builtin or bare) is flagged when it
references ``role_path`` on a line without a ``lookup(``/``query(`` call.

Per-task opt-out: add ``# nocheck: role-path-in-shell`` anywhere inside the
offending task block (grammar per
``docs/contributing/actions/testing/suppression.md``).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import PROJECT_ROOT, iter_project_files, read_text

_SCAN_DIRS: frozenset[str] = frozenset({"roles", "tasks"})

_ROLE_PATH_RE = re.compile(r"\{\{[^}]*\brole_path\b")
_ACTION_RE = re.compile(
    r"^\s*(?:-\s+)?(?:ansible\.(?:builtin|legacy)\.)?(shell|command)\s*:"
)
_NOCHECK_RE = re.compile(
    r"nocheck\s*:\s*([a-z0-9][a-z0-9\-]*(?:\s*,\s*[a-z0-9][a-z0-9\-]*)*)",
    re.IGNORECASE,
)
_NOCHECK_KEY = "role-path-in-shell"
_LIST_ITEM_RE = re.compile(r"^(\s*)-\s")


def _enclosing_block(lines: list[str], idx: int) -> tuple[int, int]:
    """Innermost list item containing line ``idx``, so a ``script:`` subtask
    inside a ``block:``/``rescue:`` is not conflated with shell siblings."""
    start = 0
    item_indent = 0
    for i in range(idx, -1, -1):
        m = _LIST_ITEM_RE.match(lines[i])
        if m:
            start = i
            item_indent = len(m.group(1))
            break
    end = len(lines)
    for i in range(idx + 1, len(lines)):
        m = _LIST_ITEM_RE.match(lines[i])
        if m and len(m.group(1)) <= item_indent:
            end = i
            break
    return start, end


def _block_name(lines: list[str], start: int, end: int) -> str:
    for i in range(start, end):
        stripped = lines[i].strip()
        if stripped.startswith(("- name:", "name:")):
            return stripped.split(":", 1)[1].strip().strip("\"'") or "<unnamed>"
    return "<unnamed>"


def _block_suppressed(block_text: str) -> bool:
    for match in _NOCHECK_RE.finditer(block_text):
        rules = {r.strip().lower() for r in match.group(1).split(",")}
        if _NOCHECK_KEY in rules:
            return True
    return False


def _block_has_shell_action(lines: list[str], start: int, end: int) -> bool:
    return any(_ACTION_RE.match(lines[i]) for i in range(start, end))


def _file_offenders(path: Path) -> list[str]:
    try:
        src = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []
    if "role_path" not in src:
        return []

    lines = src.splitlines()
    seen_blocks: set[tuple[int, int]] = set()
    offenders: list[str] = []

    for idx, line in enumerate(lines):
        match = _ROLE_PATH_RE.search(line)
        if not match:
            continue
        hash_pos = line.find("#")
        if 0 <= hash_pos < match.start():
            continue
        if "lookup(" in line or "query(" in line:
            continue
        block = _enclosing_block(lines, idx)
        if block in seen_blocks:
            continue
        start, end = block
        if not _block_has_shell_action(lines, start, end):
            continue
        seen_blocks.add(block)
        block_text = "\n".join(lines[start:end])
        if _block_suppressed(block_text):
            continue
        offenders.append(f"line {idx + 1}: task '{_block_name(lines, start, end)}'")
    return offenders


def _scan_paths() -> list[Path]:
    out: list[Path] = []
    for s in iter_project_files(extensions=(".yml", ".yaml"), exclude_tests=True):
        p = Path(s)
        rel = p.relative_to(PROJECT_ROOT)
        if rel.parts and rel.parts[0] in _SCAN_DIRS:
            out.append(p)
    return out


class TestNoRolePathInShell(unittest.TestCase):
    def test_no_role_path_in_shell_command(self) -> None:
        offenders: dict[str, list[str]] = {}
        for path in _scan_paths():
            found = _file_offenders(path)
            if found:
                offenders[str(path.relative_to(PROJECT_ROOT))] = found

        if offenders:
            formatted = "\n".join(
                f"- {file}: {entry}"
                for file, entries in sorted(offenders.items())
                for entry in entries
            )
            self.fail(
                "role_path referenced inside shell/command task bodies. "
                "role_path is a CONTROLLER path; shell/command strings execute "
                "on the (possibly delegated) target host where the checkout "
                "does not exist.\n\n"
                "Fix one of:\n"
                "  - whole script: use ansible.builtin.script with a bare "
                "filename (resolved from the role's files/ dir and copied to "
                "the target);\n"
                "  - piping into a command: keep shell/command and feed the "
                "file via stdin: \"{{ lookup('file', '<name>') }}\" (read on "
                "the controller);\n"
                "  - deliberate controller-local execution: add "
                "'# nocheck: role-path-in-shell' inside the task block.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":
    unittest.main()
