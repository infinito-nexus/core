"""Lint guard: ``# noqa`` for a bandit (``S###``) finding MUST be justified.

Background
==========
Ruff's ``S`` rules (flake8-bandit) flag security-relevant patterns:
tar extraction (``S202``), ``urlopen`` of attacker-influenceable URLs
(``S310``), ``subprocess(..., shell=True)`` (``S602``), and similar.
Suppressing one with a bare ``# noqa: S202`` silently disables the only
local signal that the line was reviewed — exactly the situation that let
``py/tarslip`` reach CodeQL.

CodeQL ignores ruff ``# noqa`` markers, so a suppressed ``S###`` keeps
producing code-scanning alerts anyway. The cheap, durable fix is to
require every security suppression to carry an inline justification, so a
reviewer (and the next reader) can see *why* it is safe.

Convention enforced here
========================
Any ``# noqa:`` marker whose code list contains a bandit ``S###`` code
MUST be followed by free-text justification on the same line, e.g.::

    tar.extractall(tmpdir)  # noqa: S202 - members validated for path traversal

A bare ``# noqa: S310`` with nothing after the code is rejected.

Ratchet
=======
Files in ``_BASELINE`` predate the rule and carry unjustified security
suppressions today; they are grandfathered so the guard can land green.
The set MUST only shrink: justify the marker (or fix the finding), then
delete the path here. New security suppressions anywhere else fail.

Caching
=======
File walk and content reads route through ``utils.cache.files``.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files, read_text

from . import PROJECT_ROOT

# Match ``(#|//) noqa: <codes>`` and capture the comma-separated code list.
_NOQA_RE = re.compile(
    r"(?:#|//)\s*noqa\s*:\s*"
    r"(?P<codes>[A-Za-z][A-Za-z0-9\-]*(?:\s*,\s*[A-Za-z][A-Za-z0-9\-]*)*)",
    re.IGNORECASE,
)

# A bandit security code: ``S`` followed by digits (S101, S202, S310, …).
_SECURITY_CODE_RE = re.compile(r"^S\d+$")


# Files that still carry an unjustified security suppression today. Burn-down
# only: justify or fix, then remove the entry. Do NOT add to this set.
_BASELINE: frozenset[str] = frozenset(
    {
        "cli/administration/deploy/dedicated/runner.py",
        "cli/administration/deploy/development/deploy.py",
        "cli/administration/deploy/development/proc.py",
        "cli/contributing/mirror/cleanup/__main__.py",
        "plugins/lookup/nginx.py",
        "roles/svc-bkp-remote-2-local/files/pull_specific_host.py",
        "roles/svc-opt-ssd-hdd/files/script.py",
        "roles/sys-ctl-cln-bkps/files/script.py",
        "roles/sys-ctl-rpr-container-soft/files/script.py",
        "roles/sys-svc-compose-ca/files/compose_ca.py",
        "roles/sys-svc-compose/files/compose.py",
        "roles/sys-svc-container/files/container.py",
        "roles/web-app-erpnext/files/scripts/apply_oidc_settings.py",
        "roles/web-app-keycloak/library/keycloak_kcadm_update.py",
        "utils/github/playwright_summary.py",
        "utils/update/docker.py",
    }
)


def _file_offenders(path: Path) -> list[tuple[int, str]]:
    """Return ``[(lineno, marker), ...]`` for unjustified security
    suppressions on this file's lines."""
    try:
        text = read_text(str(path))
    except (OSError, UnicodeDecodeError):
        return []

    findings: list[tuple[int, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for match in _NOQA_RE.finditer(line):
            codes = [c.strip() for c in match.group("codes").split(",")]
            if not any(_SECURITY_CODE_RE.match(c) for c in codes):
                continue
            # Justification = any non-whitespace text after the code list.
            if not line[match.end() :].strip():
                findings.append((lineno, match.group(0)))
    return findings


class TestSecurityNoqaJustified(unittest.TestCase):
    """Every bandit (``S###``) ``noqa`` suppression MUST carry a reason."""

    def test_security_noqa_markers_are_justified(self) -> None:
        offenders: dict[Path, list[tuple[int, str]]] = {}

        for path_str in iter_project_files(extensions=(".py",)):
            path = Path(path_str)
            try:
                rel = path.relative_to(PROJECT_ROOT).as_posix()
            except ValueError:
                continue
            if rel in _BASELINE:
                continue
            issues = _file_offenders(path)
            if issues:
                offenders[path] = issues

        if not offenders:
            return

        def rel(p: Path) -> str:
            return p.relative_to(PROJECT_ROOT).as_posix()

        lines = [
            f"{len(offenders)} file(s) suppress a bandit (S###) finding with an "
            "unjustified ``# noqa``. Append an inline reason, e.g. "
            "``# noqa: S202 - members validated for path traversal``, or fix the "
            "finding. Security suppressions must never be silent.",
            "",
        ]
        for path, issues in sorted(offenders.items()):
            lines.append(f"  - {rel(path)}:")
            for lineno, marker in issues:
                lines.append(f"      * line {lineno}: {marker}")
        self.fail("\n".join(lines))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
