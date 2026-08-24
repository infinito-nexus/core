"""Lint guard: no legacy oauth2/oidc paths in the source tree.

The SSO flavor migration collapsed ``services.oauth2.*`` and ``services.oidc.*``
into the unified ``services.sso.*`` shape and deleted
``roles/web-app-oauth2-proxy``. This test fails if any new source file
re-introduces one of those legacy strings.

Allowed islands (each line documented below):

* The requirement document itself (``docs/requirements/021-…``).
* The /tmp migration scripts produced during the migration.
* The upstream image name ``oauth2-proxy`` and the upstream config
  filename ``oauth2-proxy-keycloak.cfg`` stay as-is — they are
  upstream identifiers, not project-internal paths. The check matches
  ``services.oauth2.`` / ``services.oidc.`` (with trailing dot) so the
  literal substring ``oauth2-proxy`` is NOT triggered by the upstream
  image name.

The guard intentionally excludes binary blobs and generated artefacts.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from utils.cache.files import iter_project_files_with_content

from . import PROJECT_ROOT

LEGACY_PATTERNS = (
    re.compile(r"services\.oauth2\."),
    re.compile(r"services\.oidc\."),
    re.compile(r"web-app-oauth2-proxy"),
    re.compile(r"(?m)^oauth2:"),
    re.compile(r"(?m)^oidc:"),
)

ALLOW_PATHS = (
    "docs/requirements/021-sso-flavor-migration.md",  # nocheck: req-ref  TODO: anchor stays put
)

EXTENSIONS = {".py", ".yml", ".yaml", ".j2", ".js", ".md", ".sh", ".conf"}


def _should_check(path: Path) -> bool:
    rel = path.relative_to(PROJECT_ROOT).as_posix()
    if any(rel.startswith(p) for p in ALLOW_PATHS):
        return False
    if path.suffix not in EXTENSIONS:
        return False
    if any(part.startswith(".") for part in path.relative_to(PROJECT_ROOT).parts):
        return False
    if "node_modules" in path.parts or "__pycache__" in path.parts:
        return False
    self_rel = "tests/lint/repository/no_legacy_sso_paths/test_no_legacy_sso_paths.py"  # nocheck: self-path-reference
    return rel != self_rel


class TestNoLegacySsoPaths(unittest.TestCase):
    def test_no_legacy_oauth2_oidc_paths(self) -> None:
        offenders: list[str] = []
        for absolute, text in iter_project_files_with_content(
            extensions=tuple(EXTENSIONS)
        ):
            p = Path(absolute)
            if not _should_check(p):
                continue
            rel = p.relative_to(PROJECT_ROOT).as_posix()
            for pat in LEGACY_PATTERNS:
                if pat.search(text):
                    offenders.append(f"{rel}: matches /{pat.pattern}/")
                    break

        if offenders:
            self.fail(
                "Legacy oauth2/oidc references found:\n"
                + "\n".join(f"  - {entry}" for entry in offenders)
                + "\n\nRewrite these to the unified `services.sso.*` shape."
            )


if __name__ == "__main__":
    unittest.main()
