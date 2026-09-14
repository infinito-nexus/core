"""Lint: a task that talks to docker must come after the stack that installs it.

The image ships only ``docker-ce-cli``; the daemon is installed and started by
``sys-svc-container``, which a role pulls in through one of the ``sys-stk-*``
stacks. A docker call placed before that include therefore runs against a
socket that does not exist yet.

It fails late and unrecognisably. The play spends minutes in the constructor
and the base roles, the container reports healthy the whole time because its
probe cannot ask about a daemon that is not due yet, and the first role to
touch docker reports ``FileNotFoundError(2)`` from whatever it happened to be
doing - a network probe, in the case that produced this rule.

Swarm hides it: there the nodes are provisioned with docker before the play
reaches the role, so only the compose path fails.

The comparison is per file. A role that puts the docker call in one task file
and the stack include in another escapes, because resolving that needs the
include graph rather than two line numbers. Every current caller keeps both in
the same file, which is the shape this rule guards.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: docker-before-stack`` on, or directly above, the include.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import PROJECT_ROOT, read_text

_RULE = "docker-before-stack"

DOCKER_INCLUDES = ("sys-svc-compose/tasks/utils/network/create.yml",)

_STACK_RE = re.compile(r"name:\s*(sys-stk-[a-z-]+|sys-svc-container)")


def role_task_files() -> list:
    """Return every task file of every role, nested directories included."""
    return sorted((PROJECT_ROOT / "roles").glob("*/tasks/**/*.yml"))


def first_line(content: str, pattern) -> int:
    """Return the 1-based line of the first match, or 0.

    Args:
        content: the file's text.
        pattern: a compiled regex or a plain substring.
    """
    for index, line in enumerate(content.splitlines(), start=1):
        found = pattern.search(line) if hasattr(pattern, "search") else pattern in line
        if found:
            return index
    return 0


def calls_before_the_stack() -> list[str]:
    """Return one finding per docker call that precedes its stack include."""
    findings = []
    for path in role_task_files():
        content = read_text(str(path))
        stack = first_line(content, _STACK_RE)
        if not stack:
            continue
        for include in DOCKER_INCLUDES:
            call = first_line(content, include)
            if not call or call > stack:
                continue
            if is_suppressed_at(content.splitlines(), call, _RULE):
                continue
            rel = path.relative_to(PROJECT_ROOT)
            findings.append(
                f"{rel}:{call}: calls docker before the stack include on line "
                f"{stack} installs it"
            )
    return findings


class TestDockerCallsFollowTheStack(unittest.TestCase):
    def test_no_role_calls_docker_before_its_stack(self) -> None:
        findings = calls_before_the_stack()
        self.assertEqual(
            [],
            findings,
            f"docker call(s) that run before docker exists ({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings),
        )

    def test_the_scan_reaches_role_task_files(self) -> None:
        self.assertTrue(role_task_files(), "no role task file was scanned")

    def test_a_file_pairing_both_is_actually_reached(self) -> None:
        """Without one, the rule would pass over files it never compares."""
        paired = [
            path
            for path in role_task_files()
            for include in DOCKER_INCLUDES
            if first_line(read_text(str(path)), include)
            and first_line(read_text(str(path)), _STACK_RE)
        ]
        self.assertTrue(paired, "no task file both calls docker and loads a stack")


if __name__ == "__main__":
    unittest.main()
