"""Flag ``nfs: false`` entries in ``roles/<role>/meta/volumes.yml`` that
are not justified.

``nfs: false`` opts a volume out of the swarm NFS rewrite and keeps it
node-local. That is sometimes necessary (e.g. a store that uses
``fcntl`` locks NFS cannot serve), but it has a real cost: a node-local
volume does NOT follow a task that swarm reschedules onto another node,
so its contents are lost on a drain/reschedule. Every ``nfs: false``
therefore MUST be accompanied by an explicit justification arguing why
that data loss is acceptable here (single-replica that never moves, the
data is re-provisioned on redeploy, a backup covers the restore, the
volume holds only regenerable cache, ...).

A role whose primary entity is pinned to the swarm manager
(``placement: manager`` in ``meta/services.yml``) is exempt: it never
reschedules away from the node holding its data, so its ``nfs: false``
volumes survive and need no per-volume justification.

Convention
==========
On the ``nfs: false`` line, or on the immediately preceding contiguous
comment lines, add both markers. Keep them on one comment line so the
repository comment linter treats the whole line as a tool directive:

    # nocheck: nfs-false-data-loss  Reason: <why no data is lost, or why the loss is acceptable>
    nfs: false

The ``nocheck`` opts into the exemption; the ``Reason:`` states why.
Both are required, in either order.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_VOLUMES
from utils.roles.meta_lookup import get_role_placement

from . import PROJECT_ROOT

_RULE = "nfs-false-data-loss"

_NFS_FALSE = re.compile(r"^\s*nfs:\s*false\s*(?:#.*)?$")
_REASON = re.compile(r"#.*\breason\b\s*:\s*\S", re.IGNORECASE)


def _justification_near(lines: list[str], line_no: int) -> tuple[bool, bool]:
    """Return ``(has_nocheck, has_reason)`` for the ``nfs: false`` at the
    1-indexed ``line_no``, scanning that line and the contiguous comment
    lines directly above it. Order of the two markers within the block
    does not matter."""
    idx = line_no - 1
    if idx < 0 or idx >= len(lines):
        return False, False
    has_nocheck = line_has_rule(lines[idx], _RULE)
    has_reason = bool(_REASON.search(lines[idx]))
    scan = idx - 1
    while scan >= 0 and lines[scan].lstrip().startswith("#"):
        has_nocheck = has_nocheck or line_has_rule(lines[scan], _RULE)
        has_reason = has_reason or bool(_REASON.search(lines[scan]))
        scan -= 1
    return has_nocheck, has_reason


def _is_manager_pinned(role_name: str) -> bool:
    """True when the role's primary entity declares ``placement: manager``.
    A manager-pinned role never reschedules away from the node holding its
    data, so its node-local (``nfs: false``) volumes survive and need no
    per-volume justification."""
    try:
        placement = get_role_placement(role_name)
    except Exception:
        return False
    return (placement or "").strip().lower() == "manager"


class TestNfsFalseRequiresDataLossJustification(unittest.TestCase):
    def test_nfs_false_is_justified(self) -> None:
        findings: list[tuple[str, int, str]] = []
        roles_dir = PROJECT_ROOT / "roles"
        for role_dir in sorted(p for p in roles_dir.iterdir() if p.is_dir()):
            meta_path = role_dir / ROLE_FILE_META_VOLUMES
            if not meta_path.is_file():
                continue
            if _is_manager_pinned(role_dir.name):
                continue
            try:
                lines = read_text(str(meta_path)).splitlines()
            except (OSError, ValueError):
                continue
            rel = meta_path.relative_to(PROJECT_ROOT).as_posix()

            for idx, line in enumerate(lines):
                if not _NFS_FALSE.match(line):
                    continue
                line_no = idx + 1
                has_nocheck, has_reason = _justification_near(lines, line_no)
                if has_nocheck and has_reason:
                    continue
                missing = []
                if not has_nocheck:
                    missing.append(f"# nocheck: {_RULE}")
                if not has_reason:
                    missing.append("# Reason: <why no data is lost>")
                findings.append((rel, line_no, ", ".join(missing)))

        if findings:
            formatted = "\n".join(
                f"- {p}:{n}: missing {m}"
                for p, n, m in sorted(set(findings), key=lambda i: (i[0], i[1]))
            )
            self.fail(
                "Found 'nfs: false' entries in meta/volumes.yml that are not "
                "justified. A node-local volume does not follow a swarm "
                "reschedule, so its data is lost on drain; every 'nfs: false' "
                "MUST argue why that is acceptable here.\n\n"
                "Fix: on the 'nfs: false' line or the contiguous comment lines "
                "above it, add both markers on one comment line:\n\n"
                f"    # nocheck: {_RULE}  Reason: single-replica that never "
                "moves / re-provisioned on redeploy / backup covers restore / "
                "regenerable cache\n"
                "    nfs: false\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
