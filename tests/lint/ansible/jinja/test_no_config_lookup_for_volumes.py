"""Strict guard against the legacy ``lookup('config', app, 'volumes.X.Y')``
shape. Every volume access MUST flow through the dedicated ``volume``
lookup instead::

    lookup('volume', application_id, '<X>').<Y>

Why this is forbidden
=====================

The ``config`` lookup walks the merged application config tree, which
couples the *config* domain to the *volumes* domain: every consumer
that wants a single volume field (``.name``, ``.path``, ``.mode``)
re-enters the config plugin, inflates the per-application cache, and
implicitly pins the legacy_view compatibility layer in place. The
dedicated ``volume`` lookup resolves directly off ``meta/volumes.yml``
(the single source of truth for NFS opt-in, swarm config/secret
distribution, and reschedule-safe bind sources). Removing all
``lookup('config', …, 'volumes.…')`` call sites is the prerequisite
for deleting the legacy_view shim from the applications cache.

Per-line opt-out: ``# nocheck: legacy-volume-config-lookup`` on the
offending line or the immediately preceding non-empty line. Reserved
for the migration window only — every suppression is a debt marker
that must be paid down before the legacy_view layer can be removed.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_RULE = "legacy-volume-config-lookup"

_SCAN_PREFIXES = ("roles/", "scripts/")
_SCAN_EXTENSIONS = (".yml", ".j2", ".py")

_LEGACY_VOLUME_CONFIG_LOOKUP = re.compile(
    r"""lookup\(\s*['"]config['"]\s*,\s*[^,]+,\s*['"]volumes\.[^'"]+\.[^'"]+['"]"""
)


def _is_in_scope(rel_path: str) -> bool:
    return any(rel_path.startswith(prefix) for prefix in _SCAN_PREFIXES)


class TestNoConfigLookupForVolumes(unittest.TestCase):
    def test_no_legacy_volume_config_lookup(self) -> None:
        findings: list[tuple[str, int, str]] = []
        for path_str, content in iter_project_files_with_content(
            extensions=_SCAN_EXTENSIONS,
            exclude_tests=True,
        ):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if not _is_in_scope(rel):
                continue
            lines = content.splitlines()
            for idx, line in enumerate(lines):
                if not _LEGACY_VOLUME_CONFIG_LOOKUP.search(line):
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
                "Found legacy `lookup('config', app, 'volumes.X.Y')` calls. "
                "Volume access must go through the dedicated `volume` "
                "lookup so the config domain stays decoupled from the "
                "volumes domain and the legacy_view layer can be retired:\n\n"
                "    lookup('volume', application_id, '<X>').<field>\n\n"
                "instead of:\n\n"
                "    lookup('config', application_id, 'volumes.<X>.<field>')\n\n"
                "Mark with `# nocheck: legacy-volume-config-lookup` only "
                "for migration-window exceptions.\n\n"
                f"Offenders:\n{formatted}"
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
