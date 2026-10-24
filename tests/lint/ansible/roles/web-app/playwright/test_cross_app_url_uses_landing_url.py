"""Lint that a ``templates/playwright.env.j2`` names another application's
URL through ``lookup('landing_url', '<app>')``.

The env template renders once per network pass with ``domain`` set to the
vhost under test. ``lookup('tls', '<app>', 'url.base')`` aligns the other
application's domain to that network even where the application only hands
the network over, so the spec expects a host its browser is redirected away
from. ``landing_url`` returns the URL the browser actually lands on: the
aligned one, or the canonical one behind a handover. Spelling that choice out
inline (``lookup('tls', lookup('domain', '<app>'), 'url.base')``) is the same
decision without the SPOT and is rejected too.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

_ENV_TEMPLATE_SUFFIX = "/templates/playwright.env.j2"
_CROSS_APP_TLS_URL = re.compile(
    r"""lookup\(\s*['"]tls['"]\s*,\s*['"](?P<app>[a-z0-9-]+)['"]\s*,\s*['"]url\.base['"]"""
)
_INLINE_HANDOVER = re.compile(
    r"""lookup\(\s*['"]tls['"]\s*,\s*lookup\(\s*['"]domain['"]\s*,\s*['"](?P<app>[a-z0-9-]+)['"]\s*\)"""
)


def find_violations(path: str, content: str) -> list[str]:
    """Return one message per cross-application URL not built by landing_url.

    Args:
        path: repository-relative path of a playwright env template.
        content: its text.

    Returns:
        ``path:line: …`` messages, empty when the template is clean.
    """
    role = Path(path).parts[1]
    violations = []
    for lineno, line in enumerate(content.splitlines(), start=1):
        for pattern in (_CROSS_APP_TLS_URL, _INLINE_HANDOVER):
            for match in pattern.finditer(line):
                app = match.group("app")
                if pattern is _CROSS_APP_TLS_URL and app == role:
                    continue
                violations.append(
                    f"{path}:{lineno}: use lookup('landing_url', '{app}') instead of "
                    f"{match.group(0)}…"
                )
    return violations


class TestCrossAppUrlUsesLandingUrl(unittest.TestCase):
    def test_another_application_is_reached_through_landing_url(self) -> None:
        violations: list[str] = []
        for path_str, content in iter_project_files_with_content(extensions=(".j2",)):
            rel = Path(path_str).relative_to(PROJECT_ROOT).as_posix()
            if rel.startswith("roles/") and rel.endswith(_ENV_TEMPLATE_SUFFIX):
                violations.extend(find_violations(rel, content))
        if violations:
            self.fail(
                f"{len(violations)} cross-application URL(s) in playwright env "
                "templates bypass lookup('landing_url'):\n"
                + "\n".join(f"- {v}" for v in sorted(violations))
            )

    def test_the_role_own_url_and_landing_url_pass(self) -> None:
        self.assertEqual(
            find_violations(
                "roles/web-app-foo/templates/playwright.env.j2",
                "APP_BASE_URL={{ lookup('tls', application_id, 'url.base') }}\n"
                "SELF={{ lookup('tls', 'web-app-foo', 'url.base') }}\n"
                "BAR={{ lookup('landing_url', 'web-app-bar') }}\n",
            ),
            [],
        )

    def test_a_raw_or_inline_cross_application_url_fails(self) -> None:
        self.assertEqual(
            len(
                find_violations(
                    "roles/web-app-foo/templates/playwright.env.j2",
                    "BAR={{ lookup('tls', 'web-app-bar', 'url.base') }}\n"
                    "BAZ={{ lookup('tls', lookup('domain', 'web-app-baz'), 'url.base') }}\n",
                )
            ),
            2,
        )


if __name__ == "__main__":
    unittest.main()
