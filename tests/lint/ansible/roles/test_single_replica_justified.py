"""Lint: ``replicas: 1`` in ``roles/*/meta/services.yml`` must be justified.

Pinning a service to a single swarm replica overrides the topology-driven
default and declares that the service cannot scale horizontally. That is a
deliberate limitation (stateful app, node-local volume, file sessions, a
non-clustered datastore) and MUST be justified with a
``# nocheck: single-replica <reason>`` marker on the same line or the
immediately preceding one. A bare ``replicas: 1`` is flagged so the pin is
never applied silently: services that CAN scale should carry no replicas key
and let ``compose_replicas`` pick the topology default.

Only ``replicas: 1`` is policed. Other counts (e.g. ``replicas: 0`` to disable
a service) are out of scope.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_RULE = "single-replica"
_REPLICAS_ONE = re.compile(r"^\s*replicas:\s*1\s*(?:#.*)?$")


def _collect_findings(root: Path) -> list[tuple[str, int]]:
    findings: list[tuple[str, int]] = []
    for meta in sorted((root / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")):
        try:
            text = read_text(str(meta))
        except OSError:
            continue
        lines = text.splitlines()
        for idx, line in enumerate(lines, 1):
            if not _REPLICAS_ONE.match(line):
                continue
            if is_suppressed_at(lines, idx, _RULE, mode="same-or-above"):
                continue
            findings.append((meta.relative_to(root).as_posix(), idx))
    return findings


class TestSingleReplicaJustified(unittest.TestCase):
    def test_replicas_one_is_justified(self) -> None:
        findings = _collect_findings(PROJECT_ROOT)
        if not findings:
            return
        details = "\n".join(f"  - {path}:{line}" for path, line in findings)
        self.fail(
            f"{len(findings)} unjustified `replicas: 1` pin(s). A single-replica "
            "pin means the service cannot scale horizontally and MUST carry a "
            "`# nocheck: single-replica <reason>` marker (same line or the line "
            "above) explaining why. If the service CAN scale, drop the replicas "
            "key and let compose_replicas pick the topology default.\n"
            f"{details}"
        )


if __name__ == "__main__":
    unittest.main()
