"""Forbid writing the same mount target twice in one ``meta/volumes.yml``.

A volume that reaches several services repeats its container path once per
mount. Written out each time, the path has no single point of truth: a rename
that misses one line produces a file that still parses, still deploys, and
mounts one service somewhere nobody intended. Nothing fails until the service
looks for content that is not there.

YAML already solves this. Anchor the path on its first mount and alias it
afterwards, the way ``web-app-openproject`` and ``web-app-gitlab`` do:

    mounts:
      - service: webservice
        target: &shared_target /srv/gitlab/shared
      - service: sidekiq
        target: *shared_target

The alias is resolved by the loader, so every consumer sees the identical
string and a rename is one edit.

Only literal ``target:`` values count. An alias carries no path, so it is
invisible to this rule -- which is the point.

Per-line opt-out: ``# nocheck: volumes-target-single-spot`` on the offending
line or the immediately preceding non-empty line.
"""

from __future__ import annotations

import re
import unittest
from collections import defaultdict
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_non_ignored_files, read_text
from utils.roles.mapping import ROLE_FILE_META_VOLUMES

from . import PROJECT_ROOT

_RULE = "volumes-target-single-spot"

_TARGET = re.compile(r"^\s*target:\s*(?:&\S+\s+)?(?P<path>[^*\s#][^#]*?)\s*$")


def _is_volumes_meta(rel_path: str) -> bool:
    """A role's ``meta/volumes.yml``.

    Args:
        rel_path: repository-relative path of the candidate file.
    """
    return rel_path.startswith("roles/") and rel_path.endswith(
        f"/{ROLE_FILE_META_VOLUMES}"
    )


def _duplicate_targets(lines: list[str]) -> dict[str, list[int]]:
    """Map each literal target to the 1-based lines that spell it out.

    Args:
        lines: the file's lines, without terminators.
    """
    seen: dict[str, list[int]] = defaultdict(list)
    for idx, line in enumerate(lines):
        match = _TARGET.match(line)
        if match is None:
            continue
        if is_suppressed_at(lines, idx + 1, _RULE, mode="same-or-above"):
            continue
        seen[match.group("path")].append(idx + 1)
    return {path: at for path, at in seen.items() if len(at) > 1}


class TestVolumesTargetSingleSpot(unittest.TestCase):
    def test_no_mount_target_is_written_twice(self) -> None:
        findings: list[str] = []
        for path_str in iter_non_ignored_files(
            exclude_tests=True, extensions=(".yml",)
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_volumes_meta(rel):
                continue
            lines = read_text(path_str).splitlines()
            for path, at in sorted(_duplicate_targets(lines).items()):
                where = ", ".join(str(n) for n in at)
                findings.append(f"- {rel}: {path} written {len(at)}x (lines {where})")

        if not findings:
            return

        self.fail(
            "A mount target is spelled out more than once. Anchor it on the first "
            "mount and alias it afterwards, so a rename is one edit instead of "
            "several and cannot half-succeed:\n\n"
            "    - service: a\n"
            "      target: &shared_target /srv/app/shared\n"
            "    - service: b\n"
            "      target: *shared_target\n\n" + "\n".join(findings) + "\n\n"
            f"Per-line opt-out: `# nocheck: {_RULE}` with a reason."
        )


if __name__ == "__main__":
    unittest.main()
