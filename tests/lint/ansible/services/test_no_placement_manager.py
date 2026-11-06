"""Forbid an unjustified or misspelled ``placement`` in role ``meta/services.yml``.

Rationale
=========
The point of running a service on a Docker Swarm is to let swarm
distribute it across worker nodes. Every service that carries a
``placement`` is hard-pinned to one node role and therefore CANNOT use
the rest of the cluster, which defeats the benefit of swarm entirely. By
default services should run anywhere (no placement constraint), so swarm
can do its job.

The legitimate exceptions are rare and always architectural: the edge
proxy that has to terminate TLS at a known IP, the local registry that
backs ``docker stack deploy`` itself, or shared databases that v1 of
the swarm-NFS storage design intentionally pins to a single node until
multi-replica storage is sorted out. Each of these is a deliberate
non-default and MUST be explicitly opted-in per service.

The value is checked as well as its presence. ``deploy.yml.j2``
interpolates it straight into ``node.role == <value>``, so a typo does
not fail the deploy: it renders a constraint no node satisfies and the
service hangs unscheduled until the converge wait times out. Only the
two node roles swarm defines are accepted, and that check has no
opt-out, because a misspelling is never something a justification can
make correct. A templated value cannot be resolved here and is left to
the justification requirement alone.

Per-line opt-out
================
Add ``# nocheck: default-placement-manager`` on the same line as the
``placement`` key OR on the immediately preceding non-empty line. The
opt-out MUST be accompanied by a short comment above explaining WHY this
specific service is pinned (e.g. "edge proxy: TLS terminator on a known
node"), so reviewers can see the architectural justification without
reading the role.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "default-placement-manager"

_ALLOWED = ("manager", "worker")

_PLACEMENT = re.compile(r"^\s*placement\s*:\s*(?P<value>.*?)\s*(?:#.*)?$")


def _is_scan_target(rel_path: str) -> bool:
    return (
        rel_path.startswith("roles/")
        and "/meta/" in rel_path
        and rel_path.endswith("services.yml")
    )


def _placements() -> list[tuple[str, int, str, str, bool]]:
    """Every ``placement`` line in a role's meta/services.yml.

    Returns:
        Tuples of (relative path, 1-based line number, stripped line, the
        declared value with surrounding quotes removed, whether the line
        carries the nocheck marker).
    """
    found: list[tuple[str, int, str, str, bool]] = []
    for path_str, content in iter_project_files_with_content(
        extensions=(".yml", ".yaml"),
        exclude_tests=True,
    ):
        rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
        if not _is_scan_target(rel):
            continue
        lines = content.splitlines()
        for idx, line in enumerate(lines):
            match = _PLACEMENT.match(line)
            if not match:
                continue
            value = match.group("value").strip().strip("\"'")
            found.append(
                (
                    rel,
                    idx + 1,
                    line.strip(),
                    value,
                    is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"),
                )
            )
    return found


def _format(findings: list[tuple[str, int, str]]) -> str:
    return "\n".join(
        f"- {p}:{n}: {s}"
        for p, n, s in sorted(set(findings), key=lambda item: (item[0], item[1]))
    )


class TestNoDefaultPlacementManager(unittest.TestCase):
    def test_no_placement_without_explicit_opt_out(self) -> None:
        findings = [
            (rel, line_no, text)
            for rel, line_no, text, _value, suppressed in _placements()
            if not suppressed
        ]
        if findings:
            self.fail(
                "Found a `placement` in role meta/services.yml without an "
                "explicit nocheck opt-out. Pinning a service removes the rest "
                "of the cluster from its scheduling and defeats the benefit of "
                "swarm: the service runs only on a single node role and the "
                "remaining capacity goes unused.\n\n"
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
                f"Offending lines:\n{_format(findings)}"
            )

    def test_placement_names_a_swarm_node_role(self) -> None:
        findings = [
            (rel, line_no, text)
            for rel, line_no, text, value, _suppressed in _placements()
            if "{{" not in value and value not in _ALLOWED
        ]
        if findings:
            self.fail(
                "Found a `placement` whose value is not a swarm node role. "
                f"Swarm defines exactly {' and '.join(_ALLOWED)}, and "
                "`roles/sys-svc-container/templates/deploy.yml.j2` renders the "
                "value verbatim into `node.role == <value>`. Anything else "
                "produces a constraint no node satisfies, so the service is "
                "never scheduled and the deploy hangs in the converge wait "
                "instead of failing with a readable error.\n\n"
                "This check has no nocheck opt-out: a misspelled node role is "
                "never correct. Fix the value or remove the key.\n\n"
                f"Offending lines:\n{_format(findings)}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
