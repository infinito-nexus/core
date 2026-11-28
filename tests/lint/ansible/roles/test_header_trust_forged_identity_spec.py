"""Lint: every header-trust role runs the forged-identity Playwright probe.

A backend that logs a user in from a proxy-set header is one missing openresty
strip away from impersonation, which is how ``/healthz/ready`` opened an
administrator session. Each such role, as ``utils.roles.header_trust`` detects
it, must require ``./test-forged-identity`` from its ``playwright.spec.js``, and
that spec must drive ``probeForgedIdentity``, which forges every trusted header.
"""

from __future__ import annotations

import ast
import re
import unittest

from utils.cache.files import PROJECT_ROOT, read_text
from utils.roles.header_trust import DETECTED_HEADERS, header_trust_roles
from utils.roles.mapping import ROLE_FILE_PLAYWRIGHT_SPEC

ROLES_DIR = PROJECT_ROOT / "roles"
HELPER = (
    PROJECT_ROOT / "roles/test-e2e-playwright/files/personas/utils/forged-identity.js"
)
SPEC_NAME = "test-forged-identity.js"

INVENTORIED = frozenset(
    {
        "web-app-baserow",
        "web-app-bluesky",
        "web-app-bookwyrm",
        "web-app-checkmk",
        "web-app-n8n",
        "web-app-openproject",
        "web-app-postmarks",
        "web-app-snipe-it",
        "web-app-yourls",
    }
)

_REQUIRES_SPEC = re.compile(
    r"""require\(\s*['"]\./test-forged-identity(?:\.js)?['"]\s*\)"""
)
_DRIVES_PROBE = re.compile(r"\bprobeForgedIdentity\s*\(")
_FORGED_NAMES = re.compile(
    r"\bconst\s+FORGED_IDENTITY_HEADER_NAMES\s*=\s*Object\.freeze\(\s*(\[.*?\])\s*\)",
    re.DOTALL,
)


def forged_header_names() -> list[str]:
    """
    Returns:
        The header names ``forgedIdentityHeaders`` sets, read from the helper's
        ``FORGED_IDENTITY_HEADER_NAMES`` array literal.
    """
    match = _FORGED_NAMES.search(read_text(str(HELPER)))
    return ast.literal_eval(match.group(1)) if match else []


def unwired_roles() -> list[str]:
    """Returns one finding per header-trust role that ships without the probe."""
    findings: list[str] = []
    for role, evidence in sorted(header_trust_roles(ROLES_DIR).items()):
        suite = ROLES_DIR / role / ROLE_FILE_PLAYWRIGHT_SPEC
        spec = suite.parent / SPEC_NAME
        reason = None
        if not suite.is_file():
            reason = f"has no {ROLE_FILE_PLAYWRIGHT_SPEC}"
        elif not _REQUIRES_SPEC.search(read_text(str(suite))):
            reason = (
                f"{ROLE_FILE_PLAYWRIGHT_SPEC} does not require ./test-forged-identity"
            )
        elif not spec.is_file():
            reason = f"has no files/playwright/{SPEC_NAME}"
        elif not _DRIVES_PROBE.search(read_text(str(spec))):
            reason = f"{SPEC_NAME} never calls probeForgedIdentity"
        if reason:
            findings.append(
                f"{role}: {reason} (trusts a header in {', '.join(evidence)})"
            )
    return findings


class TestHeaderTrustForgedIdentitySpec(unittest.TestCase):
    def test_every_header_trust_role_runs_the_probe(self) -> None:  # nocheck: test.text-presence -- policy lint over every detected header-trust role  # fmt: skip
        findings = unwired_roles()
        self.assertEqual(
            [],
            findings,
            "header-trust role(s) without the forged-identity Playwright probe "
            f"({len(findings)}):\n"
            + "\n".join(f"  - {f}" for f in findings)
            + f"\n\nFix: add files/playwright/{SPEC_NAME} calling probeForgedIdentity "
            "from ./personas and require it from playwright.spec.js.",
        )

    def test_the_detection_finds_every_inventoried_role(self) -> None:
        """A detection that drifts blind would pass the rule above vacuously."""
        missed = sorted(INVENTORIED - set(header_trust_roles(ROLES_DIR)))
        self.assertEqual([], missed, "inventoried header-trust roles not detected")

    def test_the_helper_forges_every_trusted_header(self) -> None:
        forged = forged_header_names()
        for header in DETECTED_HEADERS:
            with self.subTest(header=header):
                self.assertIn(header, forged)


if __name__ == "__main__":
    unittest.main()
