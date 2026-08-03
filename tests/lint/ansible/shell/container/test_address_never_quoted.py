"""Ban ``| quote`` on ``*_CONTAINER_ADDRESS`` variables in role task
files.

Rationale
=========
The ``container_address`` lookup emits a shell fragment
``"$(/usr/bin/resolve-container-id <stack> <svc>)"`` in swarm mode. The
fragment must reach ``ansible.builtin.shell`` unquoted so the subshell
expands at exec time; piping it through ``| quote`` single-quotes it,
Docker receives the literal ``$(...)`` string, and the task fails with
"No such container". In compose mode the lookup returns a bare service
name and ``| quote`` is merely redundant.

Per-line opt-out
================
Add ``# nocheck: container-address-quote`` on the same line as the
``| quote`` usage or on the immediately preceding non-empty line.
Reserved for sites that provably never see the swarm fragment
(``DEPLOYMENT_MODE == 'compose'``-gated tasks, roles pinned via
``compose_mode_force``) or consumers that re-evaluate the argument
themselves (e.g. ``set_postgres_superuser_password.sh``).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "container-address-quote"
_QUOTED_ADDRESS = re.compile(r"\w*CONTAINER_ADDRESS\s*\|\s*quote\b")


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/"):
        return False
    if not rel_path.endswith((".yml", ".yaml")):
        return False
    return "/tasks/" in rel_path or "/handlers/" in rel_path


class TestContainerAddressNeverQuoted(unittest.TestCase):
    def test_container_address_is_never_piped_through_quote(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml")
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _QUOTED_ADDRESS.search(line):
                    continue
                line_no = idx + 1
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{ln}: {snip}"
                for p, ln, snip in sorted(set(findings), key=lambda x: (x[0], x[1]))
            )
            self.fail(
                "Found `*_CONTAINER_ADDRESS | quote` in role task files. In "
                "swarm mode the `container_address` lookup emits a `$(...)` "
                "shell fragment that must stay unquoted so the subshell "
                "expands at exec time; `| quote` hands Docker the literal "
                "string and the task fails with 'No such container'.\n\n"
                "Fix one of:\n"
                "  - drop `| quote` and embed the variable bare in an "
                "`ansible.builtin.shell` command;\n"
                "  - for sites that provably never see the swarm fragment "
                "(compose-gated task or `compose_mode_force` role), add "
                "`# nocheck: container-address-quote` on the same line or "
                "the line above.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
