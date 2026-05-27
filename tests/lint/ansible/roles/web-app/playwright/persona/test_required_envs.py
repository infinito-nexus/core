"""Lint: every role whose `templates/playwright.env.j2` ships
`DASHBOARD_SERVICE_ENABLED=` MUST also render `MATOMO_BASE_URL` so the
shared persona helpers can actually compose CSP allow-list checks.

Why
---

The CSP helper at
``roles/test-e2e-playwright/files/personas/utils/csp.js`` reads
``process.env.MATOMO_BASE_URL`` to whitelist the Matomo origin when the
persona navigates an SSO-gated app. A role that declares
``dashboard: enabled`` but forgets to render ``MATOMO_BASE_URL`` makes
that whitelist empty, which causes the persona CSP probe to flag every
Matomo request as a violation even though Matomo is the intended
destination.

Suppression
-----------

A role MAY opt out per env line via
``# nocheck: persona-required-envs`` placed on the same line as the
``DASHBOARD_SERVICE_ENABLED=...`` declaration or in the comment block
immediately above it. Use only for genuinely auth-less svc-* roles
that still need the dashboard flag for compatibility.
"""

from __future__ import annotations

import re
import unittest

from utils.annotations.suppress import is_suppressed_at
from utils.cache.files import read_text

from . import PROJECT_ROOT

ROLES_DIR = PROJECT_ROOT / "roles"
_ENV_TEMPLATE_REL = "templates/playwright.env.j2"  # nocheck: role-file-spot
_DASHBOARD_FLAG_RE = re.compile(r"^\s*DASHBOARD_SERVICE_ENABLED\s*=", re.MULTILINE)
_REQUIRED_URLS: tuple[str, ...] = ("MATOMO_BASE_URL",)
_RULE = "persona-required-envs"


class TestPersonaRequiredEnvs(unittest.TestCase):
    def test_dashboard_flag_implies_persona_base_urls(self):
        offenders: list[str] = []

        for role_dir in sorted(p for p in ROLES_DIR.iterdir() if p.is_dir()):
            env_path = role_dir / _ENV_TEMPLATE_REL
            if not env_path.is_file():
                continue
            text = read_text(str(env_path))
            m = _DASHBOARD_FLAG_RE.search(text)
            if not m:
                continue

            line_no = text[: m.start()].count("\n") + 1
            env_lines = text.splitlines()
            if is_suppressed_at(env_lines, line_no, _RULE):
                continue

            for url in _REQUIRED_URLS:
                if re.search(rf"^\s*{re.escape(url)}\s*=", text, re.MULTILINE):
                    continue
                offenders.append(
                    f"{role_dir.name}: {_ENV_TEMPLATE_REL} declares "
                    f"`DASHBOARD_SERVICE_ENABLED=` but does NOT render `{url}=`. "
                    f"The persona helpers gate on this URL being non-empty; "
                    f"without it the persona scenario silently SKIPS instead of "
                    f"running. Render the URL via "
                    f"`{url}={{{{ lookup('tls', '<provider-role>', 'url.base') | dotenv_quote }}}}` "
                    f"or mark the dashboard flag with "
                    f"`# nocheck: {_RULE}` if the role is genuinely auth-less."
                )

        if offenders:
            self.fail(
                "Persona-required base URLs missing:\n"
                + "\n".join(f"  - {o}" for o in offenders)
            )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
