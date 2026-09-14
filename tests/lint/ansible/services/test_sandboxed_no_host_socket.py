"""Lint: a sandboxed workload never gets the host container socket.

A role that pins ``SANDBOX_RUNTIME`` on its service does so because it executes
code a model wrote. Handing that container ``/var/run/docker.sock`` gives it the
host daemon, which can start a privileged container on the host kernel — the
isolating runtime is then decoration, and the deploy stays green while the
sandbox is gone.

The scan derives the sandboxed set from the templates that pin the runtime, so
a third agent added later is covered without touching this file.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: sandboxed-no-host-socket`` on the offending line or the
  non-empty line above it.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "sandboxed-no-host-socket"
_RUNTIME_PIN = "SANDBOX_RUNTIME"
_HOST_SOCKET = "/var/run/docker.sock"
_RUNTIME_OWNER = "sys-svc-container"


def _role_of(path: str) -> str | None:
    roles_prefix = str(PROJECT_ROOT / "roles") + os.sep
    if not path.startswith(roles_prefix):
        return None
    return path[len(roles_prefix) :].split(os.sep, 1)[0]


def _sandboxed_roles() -> set[str]:
    """Return the roles whose own templates pin the sandbox runtime."""
    roles: set[str] = set()
    for path, content in iter_project_files_with_content(
        extensions=(".j2",), exclude_tests=True
    ):
        role = _role_of(path)
        if role is None or role == _RUNTIME_OWNER:
            continue
        if "/templates/" in Path(path).as_posix() and _RUNTIME_PIN in content:
            roles.add(role)
    return roles


class TestSandboxedNoHostSocket(unittest.TestCase):
    def test_no_sandboxed_role_mounts_the_host_socket(self) -> None:
        sandboxed = _sandboxed_roles()
        findings: list[str] = []
        for path, content in iter_project_files_with_content(exclude_tests=True):
            role = _role_of(path)
            if role not in sandboxed:
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if _HOST_SOCKET not in line:
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                rel = Path(path).relative_to(PROJECT_ROOT).as_posix()
                findings.append(f"{rel}:{idx + 1}: {line.strip()}")

        self.assertEqual(
            [],
            sorted(findings),
            f"sandboxed role(s) reaching the host container socket "
            f"({len(findings)}); the isolating runtime cannot contain a "
            f"container that can drive the host daemon:\n"
            + "\n".join(f"  - {f}" for f in sorted(findings)),
        )

    def test_the_scan_finds_sandboxed_roles(self) -> None:
        self.assertTrue(
            _sandboxed_roles(),
            f"no role template pins {_RUNTIME_PIN}, so the rule would pass "
            "vacuously; check that the scan still reads the right topic",
        )


if __name__ == "__main__":
    unittest.main()
