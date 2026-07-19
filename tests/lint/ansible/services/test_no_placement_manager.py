"""Forbid ``placement: manager`` in role ``meta/services.yml``.

Rationale
=========
The point of running a service on a Docker Swarm is to let swarm
distribute it across worker nodes. Every service that carries
``placement: manager`` is hard-pinned to the manager node and
therefore CANNOT use any worker, which defeats the benefit of swarm
entirely. By default services should run anywhere (no placement
constraint), so swarm can do its job.

The legitimate exceptions are rare and always architectural: the edge
proxy that has to terminate TLS at a known IP, the local registry that
backs ``docker stack deploy`` itself, or shared databases that v1 of
the swarm-NFS storage design intentionally pins to a single node until
multi-replica storage is sorted out. Each of these is a deliberate
non-default and MUST be explicitly opted-in per service.

Per-line opt-out
================
Add ``# nocheck: default-placement-manager`` on the same line as
``placement: manager`` OR on the immediately preceding
non-empty line. The opt-out MUST be accompanied by a short comment
above explaining WHY this specific service is pinned to the manager
(e.g. "edge proxy: TLS terminator on a known node"), so reviewers can
see the architectural justification without reading the role.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "default-placement-manager"

_DEFAULT_PLACEMENT_MANAGER = re.compile(
    r"^\s*placement\s*:\s*['\"]?manager['\"]?\s*(?:#.*)?$"
)


def _is_scan_target(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/meta/" in rel_path
        and rel_path.endswith("services.yml")
    )


class TestNoDefaultPlacementManager(unittest.TestCase):
    def test_no_placement_manager_without_explicit_opt_out(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=(".yml", ".yaml"),
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_scan_target(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _DEFAULT_PLACEMENT_MANAGER.match(line):
                    continue
                if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
                    continue
                findings.append((rel, idx + 1, line.strip()))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: {s}"
                for p, n, s in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found `placement: manager` in role meta/services.yml "
                "without an explicit nocheck opt-out. Pinning a service to the "
                "swarm manager removes the worker pool from its scheduling and "
                "defeats the benefit of swarm: the service runs only on a "
                "single node and worker capacity goes unused.\n\n"
                "Default: drop the line. Services should run anywhere so swarm "
                "distributes them. Where additional capacity / replication is "
                "needed, pair the bare service with `compose_replicas` or "
                "`deploy.mode: global` instead of pinning.\n\n"
                "Legitimate exceptions (edge proxy that terminates TLS at a "
                "known IP, local registry that backs `docker stack deploy`, "
                "shared databases that v1 storage design pins until multi-"
                "replica storage is sorted out, etc.) MUST add a one-line "
                "architectural justification comment above the line plus the "
                "marker `# nocheck: default-placement-manager`. Example:\n\n"
                "    # nocheck: default-placement-manager  edge proxy must "
                "terminate TLS at the manager IP (no overlay-routable VIP yet)\n"
                "    placement: manager\n\n"
                f"Offending lines:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
