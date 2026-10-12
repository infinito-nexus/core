"""Ban a credential handed to a container command as a bare flag argument.

Rationale
=========
``container exec … --password {{ SOME_PASSWORD }}`` renders the secret into
the argv of the host-side process, where ``ps`` shows it to every local
account for as long as the call runs. ``no_log`` masks Ansible's output, not
the process table.

This is the sibling of ``container-exec-env-value``, which covers
``-e NAME=VALUE``. The leak is the same; only the syntax differs, and a rule
written for one spelling is silent on the other.

The signal is the value, never the flag. ``-p`` means "parents" to ``mkdir``,
a vhost to ``rabbitmqctl`` and a port to ``turnutils_stunclient``, so a rule
keyed on flag names would be noise. A dash-flag immediately followed by a
Jinja expression that reads a credential is the shape that leaks, and nothing
else matches it.

The remedy, in order of preference
==================================
1. Hand the value over on **stdin**, where it reaches no argv at all.
   ``curl -K -`` does this, as ``web-app-stalwart/tasks/jmap_call.yml`` shows.
2. Otherwise ``-e NAME`` plus the task's ``environment:``, with ``"$NAME"``
   inside an ``sh -lc`` wrapper so the container's shell expands it. The
   secret leaves the host argv but remains in the in-container process's.

Scope is task files and shell payloads. A compose ``command:`` is the
container's own argv in a file the deploy protects, which is a different
exposure.

Per-line opt-out
================
``# nocheck: container-flag-credential -- <reason>`` on the same line or the
immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "container-flag-credential"
_EXTENSIONS = (".yml", ".yaml", ".sh")
_CREDENTIAL = (
    r"_PASSWORD\b"
    r"|_PASS\b"
    r"|_PWD\b"
    r"|\.password\b"
    r"|secrets\.credentials\."
    r"|['\"]password['\"]"
    r"|BIND_CREDENTIAL"
    r"|CLIENT\.SECRET"
)
_FLAG_WITH_CREDENTIAL = re.compile(
    r"(?<!\S)(--?[A-Za-z][A-Za-z0-9-]*)[= ]\s*\{\{[^}]*(?:" + _CREDENTIAL + r")"
)


def _is_scan_target(rel_path: str) -> bool:
    if not rel_path.startswith("roles/") or not rel_path.endswith(_EXTENSIONS):
        return False
    return "/tasks/" in rel_path or "/files/" in rel_path


class TestContainerFlagPassesNoCredential(unittest.TestCase):
    def test_no_credential_is_handed_over_as_a_flag_argument(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=_EXTENSIONS
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if line.lstrip().startswith("#"):
                    continue
                match = _FLAG_WITH_CREDENTIAL.search(line)
                if not match:
                    continue
                line_no = idx + 1
                if is_suppressed_at(lines, line_no, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, line_no, line.strip()[:80]))

        if findings:
            formatted = "\n".join(
                f"- {p}:{ln}: {snip}"
                for p, ln, snip in sorted(set(findings), key=lambda x: (x[0], x[1]))
            )
            self.fail(
                f"Found {len(set(findings))} credential(s) handed to a command as a "
                "flag argument. The value renders into the argv of the host-side "
                "process, where `ps` shows it to every local account while the "
                "call runs, and `no_log` cannot mask a process table.\n\n"
                "Fix one of:\n"
                "  - give the value to the program on stdin, which keeps it out "
                "of every argv; `curl -K -` is the form "
                "roles/web-app-stalwart/tasks/jmap_call.yml already uses;\n"
                "  - forward it as `-e NAME` with the value in the task's "
                "`environment:`, and reference `\"$NAME\"` inside an `sh -lc` "
                "wrapper so the container's shell expands it, not the host's;\n"
                "  - add `# nocheck: container-flag-credential -- <reason>` where "
                "the value provably carries no secret.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
