"""A ``# nocheck: docker-version`` marker sits where the image updater reads it.

The updater only skips a ``version:`` whose own line or immediately preceding
non-empty line carries the marker (``utils/update/docker.py``). One line too
high, above ``image:``, the marker holds nothing: the updater moved the
self-built bases of ``svc-ai-s1`` and ``svc-ai-nllb-engine`` to
``python:3.15.2-slim``, where their pinned dependencies do not install.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import line_has_rule
from utils.cache.files import read_text
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

_RULE = "docker-version"
_VERSION_LINE = re.compile(r"^\s*version\s*:")


def _misplaced() -> list[str]:
    findings: list[str] = []
    for config_path in sorted(
        (PROJECT_ROOT / "roles").glob(f"*/{ROLE_FILE_META_SERVICES}")
    ):
        lines = read_text(str(config_path)).splitlines()
        for index, line in enumerate(lines):
            if not line_has_rule(line, _RULE) or _VERSION_LINE.match(line):
                continue
            following = next((text for text in lines[index + 1 :] if text.strip()), "")
            if not _VERSION_LINE.match(following):
                findings.append(
                    f"- {config_path.relative_to(PROJECT_ROOT)}:{index + 1} "
                    f"is followed by '{following.strip()}'"
                )
    return findings


class TestDockerVersionMarkerPlacement(unittest.TestCase):
    def test_every_marker_sits_directly_above_a_version_key(self) -> None:
        findings = _misplaced()
        self.assertEqual(
            findings,
            [],
            f"These '# nocheck: {_RULE}' markers do not sit on or directly "
            "above a 'version:' key, so the image updater still bumps that "
            "pin. Move each marker to the line right above 'version:':\n"
            + "\n".join(findings),
        )


if __name__ == "__main__":
    unittest.main()
