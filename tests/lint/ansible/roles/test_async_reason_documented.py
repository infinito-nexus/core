"""Every task that sets ``async`` MUST carry a ``# rationale: async; ...`` comment
inside the task, stating on one line why firing it off is safe.

``async`` with ``poll: 0`` is fire and forget: the play moves on while the
command is still running. That is a deployment-wide decision, not a local
one, and two properties have to hold before it is safe:

* It must hold in SWARM. A delegated command crosses a node boundary and
  runs far longer than the same command in compose, so a window that never
  opens on one node routinely opens across three. Anything the play reads
  afterwards - a config value, a group membership, an installed plugin -
  may not be written yet.
* It must be PLAYWRIGHT compatible. The e2e run starts as soon as the play
  finishes. A background command that is still writing when the browser
  arrives shows up as a flaky spec, not as a failed task, and costs an hour
  of CI to attribute.

The comment therefore has to answer one question: what reads the result of
this task, and why is it fine that the result is not there yet? An answer
of the shape "nothing downstream consumes it" is valid. "It is slow" is
not - slow is why async is tempting, not why it is safe.

Write it as ONE line directly above the ``async`` key:

    - name: ...
      # rationale: async; no register and no notify, nothing can read it back
      async: ...

``rationale:`` is a marker the comment lint accepts, so this does not count as
narration. There is no ``nocheck`` escape: the requirement is one sentence, and
a task that cannot be given one has not earned its ``async``.

``async`` and ``poll`` must also be switched off by the SAME condition. The rule
reads the gate each key states inline - the test of an ``if ... else omit`` or
the left side of a ``| ternary(..., omit)`` - and requires the two to match. A
key that names no gate matches another that names none, since both then inherit
whatever the referenced variables do.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"

_ASYNC_RE = re.compile(r"^(\s*)async:")
_POLL_RE = re.compile(r"^(\s*)poll:")
_TASK_START_RE = re.compile(r"^\s*-\s")
_REASON_RE = re.compile(r"#\s*rationale:\s*async;\s*\S")
_OMIT_RE = re.compile(r"\bomit\b")
_IF_ELSE_OMIT_RE = re.compile(r"if\s+(.+?)\s+else\s+omit")
_TERNARY_OMIT_RE = re.compile(r"\{\{\s*(.+?)\s*\|\s*ternary\(")


def _task_files():
    for candidate in sorted(iter_project_files(extensions=(".yml",))):
        path = Path(candidate)
        if ROLES_DIR not in path.parents:
            continue
        if {"files", "meta", "templates"} & set(path.parts):
            continue
        yield path


def _gate(line: str) -> str | None:
    """The off-switch a key states inline, normalised, or None when it states none.

    Args:
        line: the ``async:`` or ``poll:`` line.
    """
    if not _OMIT_RE.search(line):
        return None
    match = _IF_ELSE_OMIT_RE.search(line) or _TERNARY_OMIT_RE.search(line)
    return " ".join(match.group(1).split()) if match else "omit"


def _enclosing_task(lines: list[str], index: int) -> list[str]:
    """Return the lines of the task containing ``lines[index]``.

    Args:
        lines: all lines of the file.
        index: index of the ``async:`` line.
    """
    start = index
    while start > 0 and not _TASK_START_RE.match(lines[start]):
        start -= 1
    end = index + 1
    while end < len(lines) and not _TASK_START_RE.match(lines[end]):
        end += 1
    return lines[start:end]


class TestAsyncReasonDocumented(unittest.TestCase):
    def test_every_async_states_why_it_is_safe(self):
        offenders: list[str] = []

        for path in _task_files():
            lines = read_text(str(path)).splitlines()
            for i, line in enumerate(lines):
                if not _ASYNC_RE.match(line):
                    continue
                block = _enclosing_task(lines, i)
                if any(_REASON_RE.search(entry) for entry in block):
                    continue
                name = next(
                    (
                        entry.split("name:", 1)[1].strip().strip("\"'")
                        for entry in block
                        if "name:" in entry
                    ),
                    "<unnamed>",
                )
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{i + 1}: {name[:60]}"
                )

        self.assertEqual(
            [],
            offenders,
            "async without a '# rationale: async; ...' line stating why it is safe.\n"
            "It has to hold in swarm (delegated commands run long and cross nodes) "
            "and stay playwright compatible (the e2e run starts when the play ends, "
            "so a command still writing in the background surfaces as a flaky spec).\n"
            + "\n".join(f"  {o}" for o in offenders),
        )

    def test_async_and_poll_are_gated_by_the_same_condition(self):
        offenders: list[str] = []

        for path in _task_files():
            lines = read_text(str(path)).splitlines()
            for i, line in enumerate(lines):
                if not _ASYNC_RE.match(line):
                    continue
                block = _enclosing_task(lines, i)
                poll = next((e for e in block if _POLL_RE.match(e)), None)
                if poll is None:
                    continue
                if _gate(line) == _gate(poll):
                    continue
                offenders.append(
                    f"{path.relative_to(PROJECT_ROOT)}:{i + 1}: "
                    f"{line.strip()} / {poll.strip()}"
                )

        self.assertEqual(
            [],
            offenders,
            "async and poll must be switched off together.\n"
            "Gating only poll leaves the task on the async_wrapper path with "
            "ansible's built-in 15s poll, which collects the job and then runs "
            "async_status mode=cleanup - deleting the job file a later reap "
            "still expects to read, so a successful command reports as a "
            "failed async job.\n" + "\n".join(f"  {o}" for o in offenders),
        )


if __name__ == "__main__":
    unittest.main()
