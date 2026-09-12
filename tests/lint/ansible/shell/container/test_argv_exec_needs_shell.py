"""Enforce that a ``container_address``-derived target is only ever
reached through a module that runs a shell.

Rationale
=========
The ``container_address`` lookup does not return a container name in
swarm mode. It returns a shell fragment --
``"$(/usr/bin/resolve-container-id <stack> <service>)"`` -- that only
becomes a name once an interpreter evaluates the command substitution.

``ansible.builtin.shell`` provides that interpreter.
``ansible.builtin.command`` does not: it execs the binary directly, so
the fragment arrives at ``container exec`` as 47 literal characters and
the call dies with ``No such container: $(...)``.

Compose hides the whole class of bug, because there the same lookup
returns the bare name and ``command:`` works fine. The failure appears
only in swarm, which is why ``container-exec-resolver`` -- which checks
that the resolver is *used* -- happily passes over it. This rule checks
the other half: that something can *evaluate* what the resolver
returned.

An ``argv:`` list whose first element is an interpreter
(``bash -lc '...'``) is not matched, because the sibling rule's target
parser only recognises ``container``/``docker`` in first position; such
a task does have a shell and is correct.

Per-line opt-out
================
Add ``# nocheck: container-address-needs-shell`` on the ``argv:`` item
holding the container target, or on the line immediately above it. The
legitimate case is a role pinned to compose through
``compose_mode_force``, where the lookup can only ever yield a bare
name.
"""

from __future__ import annotations

import unittest
from pathlib import Path

import yaml

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT
from .test_exec_uses_resolver import (
    _argv_exec_target,
    _classify_target,
    _collect_approved_variables,
    _collect_argv_item_lists,
)

_RULE = "container-address-needs-shell"


def _is_scan_target(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and rel_path.endswith((".yml", ".yaml"))
        and ("/tasks/" in rel_path or "/handlers/" in rel_path)
    )


def _targets_approved_variable(token: str, approved: set[str]) -> bool:
    return _classify_target(token, approved).startswith("ok-")


class TestArgvExecNeedsShell(unittest.TestCase):
    def test_resolver_targets_are_never_reached_through_argv(self) -> None:
        approved = _collect_approved_variables()
        findings: list[tuple[str, int, str]] = []

        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue

            try:
                docs = list(yaml.compose_all(content, Loader=yaml.SafeLoader))
            except yaml.YAMLError:
                continue

            item_lists: list[list[tuple[int, str]]] = []
            for doc in docs:
                if doc is not None:
                    _collect_argv_item_lists(doc, item_lists)

            lines = content.splitlines()
            for items in item_lists:
                target = _argv_exec_target(items)
                if target is None:
                    continue
                line_no, token = target
                if not _targets_approved_variable(token, approved):
                    continue
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, lines[line_no - 1].strip()))

        if findings:
            formatted = "\n".join(
                f"- {path}:{line_no}: {snippet}"
                for path, line_no, snippet in sorted(
                    set(findings), key=lambda item: (item[0], item[1])
                )
            )
            self.fail(
                "Found `container exec` calls that address a "
                "container_address-derived variable from an `argv:` list. "
                "The lookup returns a shell fragment in swarm mode "
                "(`$(/usr/bin/resolve-container-id ...)`), and the command "
                "module runs no shell, so the fragment is passed through "
                "literally and the call fails with `No such container`. "
                "Compose hides this: there the lookup yields a bare name.\n\n"
                "Fix: use the shell module and leave the address "
                "unquoted, so the substitution can run:\n\n"
                "    - ansible.builtin.shell: >\n"
                "        container exec --user {{ X_USER }} {{ X_ADDR }}\n"
                "        cmd --flag={{ item.value | quote }}\n\n"
                "Quote the surrounding values, never the address itself.\n\n"
                "Where the role is pinned to compose via "
                "`compose_mode_force`, add "
                "`# nocheck: container-address-needs-shell` on the "
                "container target item.\n\n"
                f"Offending lines:\n{formatted}"
            )
