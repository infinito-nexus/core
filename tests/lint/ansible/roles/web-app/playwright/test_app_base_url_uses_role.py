"""Lint that every role's ``templates/playwright.env.j2`` declares
``APP_BASE_URL`` as a reference to the role's own public surface, not
some sibling role (in particular not the dashboard).

WHY: ``APP_BASE_URL`` feeds two consumers — the shared guest-persona
helper (``roles/test-e2e-playwright/files/personas/guest.js`` reads
``process.env.APP_BASE_URL`` and treats it as the role's canonical
surface) and Playwright's global ``baseURL``. A role that hardcodes a
sibling role name here makes the guest test visit the wrong site, and
in any matrix variant where that sibling is not deployed the visit
fails with ``ERR_SSL_UNRECOGNIZED_NAME_ALERT``.

Allowed forms:

* The canonical lookup against ``application_id``, e.g.
  ``{{ lookup('tls', application_id, 'url.base') ... }}`` (filters,
  whitespace, and ``regex_replace`` chains are permitted).
* A documented per-role exception declared in ``_ALLOWED_EXCEPTIONS``
  below — currently the dashboard role itself (whose
  ``DASHBOARD_APPLICATION_ID`` constant resolves to its own id) and a
  small set of roles whose canonical surface lives at a value that
  cannot be expressed as ``lookup('tls', application_id, ...)``.

Rejected: ``lookup('tls', '<sibling-role>', ...)``, raw URLs, and any
expression that does not match one of the allowed forms.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

from utils.cache.files import read_text

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_APP_BASE_URL_LINE_RE = re.compile(r"^APP_BASE_URL\s*=\s*(.*?)\s*$", re.MULTILINE)
_CANONICAL_LOOKUP_RE = re.compile(
    r"""\{\{\s*lookup\(\s*['"]tls['"]\s*,\s*application_id\s*,"""
)

# Per-role waivers. The value documents *why* the role legitimately
# deviates from the canonical pattern. Adding an entry here is the
# explicit contract that the role's canonical surface really cannot be
# expressed as ``lookup('tls', application_id, 'url.base')``.
_ALLOWED_EXCEPTIONS: dict[str, str] = {
    "web-app-dashboard": (
        "uses the role-internal DASHBOARD_APPLICATION_ID constant, which "
        "resolves to the role's own application id"
    ),
    "web-app-opencloud": (
        "uses the OPENCLOUD_URL constant — the canonical surface is a "
        "sub-path the generic tls/url.base lookup cannot express"
    ),
    "web-app-opentalk": (
        "uses the OPENTALK_URL constant — the canonical surface is a "
        "sub-path the generic tls/url.base lookup cannot express"
    ),
}


def _has_canonical_lookup(rhs: str) -> bool:
    return _CANONICAL_LOOKUP_RE.search(rhs) is not None


class TestPlaywrightAppBaseUrlUsesRole(unittest.TestCase):
    def test_app_base_url_targets_the_role_itself(self):
        root: Path = PROJECT_ROOT
        roles_dir = root / "roles"

        violations: list[str] = []

        for env_path in sorted(roles_dir.glob("*/templates/playwright.env.j2")):
            # nocheck: project-root-import  walking from a discovered glob match (<role>/templates/...) up to its role dir, not the repo root
            role_dir = env_path.parents[1]
            role_name = role_dir.name
            env_rel = env_path.relative_to(root).as_posix()
            body = read_text(str(env_path))
            match = _APP_BASE_URL_LINE_RE.search(body)

            # Omitting APP_BASE_URL is permitted: the shared guest persona
            # helper skips cleanly for auth-less roles whose env exposes
            # neither CANONICAL_DOMAIN nor APP_BASE_URL (see
            # roles/test-e2e-playwright/files/personas/guest.js).
            if match is None:
                continue

            rhs = match.group(1)
            if _has_canonical_lookup(rhs):
                continue
            if role_name in _ALLOWED_EXCEPTIONS:
                continue

            violations.append(
                f"{role_name}: {env_rel} declares APP_BASE_URL as {rhs!r}; "
                f"expected lookup('tls', application_id, 'url.base') or a documented "
                f"per-role exception in _ALLOWED_EXCEPTIONS"
            )

        if violations:
            self.fail(
                f"{len(violations)} playwright.env.j2 file(s) declare APP_BASE_URL "
                f"in a way that does not target the role's own surface:\n"
                + "\n".join(f"- {v}" for v in violations)
            )


if __name__ == "__main__":
    unittest.main()
