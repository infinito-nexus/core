"""Forbid host escapes in the ``compose.yml.j2`` of a sandboxed role.

Rationale
=========
A role that declares a ``kata`` service runs its workload under an
isolating runtime, because the workload executes code the model wrote.
Every directive that reaches back into the host namespace cancels that
isolation while leaving the promise in place:

* ``privileged: true`` grants every device and capability, which makes a
  device allowlist decorative.
* ``network_mode: host``, ``pid: host``, ``ipc: host`` and
  ``userns_mode: host`` put the workload back into a host namespace.
* mounting ``/var/run/docker.sock`` hands the workload the host engine,
  which is a root shell in one API call.

An unenforced isolation claim is the defect this tier already shipped
once: three agent replicas ran under the shared kernel while every test
was green.

Per-line opt-out
================
Add ``# nocheck: sandbox-host-escape`` on the offending line or on the
immediately preceding non-empty line, together with the reason the
escape is safe for this specific service.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "sandbox-host-escape"

_KATA_SERVICE = re.compile(r"^kata:\s*$", re.MULTILINE)

_ESCAPES = (
    (re.compile(r"^\s*privileged:\s*[\"']?true[\"']?"), "privileged: true"),
    (re.compile(r"^\s*network_mode:\s*[\"']?host[\"']?"), "network_mode: host"),
    (re.compile(r"^\s*pid:\s*[\"']?host[\"']?"), "pid: host"),
    (re.compile(r"^\s*ipc:\s*[\"']?host[\"']?"), "ipc: host"),
    (re.compile(r"^\s*userns_mode:\s*[\"']?host[\"']?"), "userns_mode: host"),
    (re.compile(r"docker\.sock"), "host docker socket bind"),
)


def _sandboxed_roles() -> set[str]:
    roles: set[str] = set()
    for path_str, content in iter_project_files_with_content(
        extensions=(".yml",),
        exclude_tests=True,
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not rel.startswith("roles/") or not rel.endswith(
            "/" + ROLE_FILE_META_SERVICES
        ):
            continue
        if _KATA_SERVICE.search(content):
            roles.add(rel.split("/")[1])
    return roles


class TestSandboxNoHostEscape(unittest.TestCase):
    def test_sandboxed_roles_do_not_escape_to_the_host(self) -> None:
        sandboxed = _sandboxed_roles()
        self.assertTrue(
            sandboxed,
            "No role declares a kata service, so this rule can never fire. "
            "Either the sandbox tier was removed or the detection broke.",
        )

        findings: list[tuple[str, int, str, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".j2",),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            parts = rel.split("/")
            if len(parts) < 2 or parts[0] != "roles" or parts[1] not in sandboxed:
                continue
            if "/templates/" not in rel or not rel.endswith("compose.yml.j2"):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                for pattern, label in _ESCAPES:
                    if not pattern.search(line):
                        continue
                    if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                        continue
                    findings.append((rel, idx + 1, label, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {label} -> {src}"
                for p, n, label, src in sorted(
                    set(findings), key=lambda i: (i[0], i[1])
                )
            )
            self.fail(
                "A role that declares a kata service runs model-written code "
                "under an isolating runtime. The directives below hand that "
                "workload back to the host and cancel the isolation while the "
                "role keeps promising it.\n\n"
                "Fix: grant the narrowest thing that works. Map individual "
                "devices instead of `privileged: true`, publish ports instead "
                "of joining the host network, and give the workload its own "
                "container daemon instead of the host socket.\n\n"
                "Mark with `# nocheck: sandbox-host-escape` plus the reason "
                "only when the escape is genuinely required and the role "
                "README states that the isolation claim does not hold.\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
