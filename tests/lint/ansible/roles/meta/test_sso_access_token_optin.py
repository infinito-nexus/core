"""Lint guard: the SSO gate hands an upstream a bearer token only on request.

``roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2``
sets ``X-Forwarded-Access-Token`` only where the consumer declares
``services.sso.oauth2.pass_access_token: true``. Two failure modes follow, and
this lint pins both:

* A role reads the header without declaring the opt-in. The gate then blanks
  the header and the role's identity handling silently degrades, in a code path
  no unit test reaches.
* A role declares the opt-in without reading the header. The token is a
  full-scope bearer for the signed-in user, so every extra recipient widens
  what a compromised container can do, and its length (which grows with the
  realm's registered origins) re-enters the upstream's header-size limit.

Suppression (see ``docs/contributing/actions/testing/suppression.md``):

* ``# nocheck: sso-access-token-optin`` in the head of ``meta/services.yml``,
  naming why the role needs the token without a readable reference to it.
"""

from __future__ import annotations

import re
import unittest
from typing import TYPE_CHECKING

import yaml

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import iter_project_files_with_content, read_text
from utils.cache.yaml import load_yaml_str
from utils.roles.mapping import ROLE_FILE_META_SERVICES

from . import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

_RULE = "sso-access-token-optin"

ROLES_DIR = PROJECT_ROOT / "roles"
GATE = PROJECT_ROOT / (
    "roles/web-app-keycloak/templates/sso_proxy/following_directives.conf.j2"
)
_HEADER_RE = re.compile(r"x[-_]forwarded[-_]access[-_]token", re.IGNORECASE)
_EMITS_RE = re.compile(r"proxy_set_header|auth_request_set")
_SKIP_DIRS = {".git", "node_modules", "__pycache__"}
_TEXT_SUFFIXES = {
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".py",
    ".rb",
    ".php",
    ".sh",
    ".lua",
    ".yml",
    ".yaml",
    ".j2",
    ".conf",
    ".json",
    ".env",
}


def _load_services(role_dir: Path):
    path = role_dir / ROLE_FILE_META_SERVICES
    if not path.is_file():
        return None, ""
    try:
        text = read_text(str(path))
    except UnicodeDecodeError:
        return None, ""
    if not text.strip():
        return None, ""
    try:
        return load_yaml_str(text), text
    except yaml.YAMLError:
        return None, text


def _declares_opt_in(services) -> bool:
    if not isinstance(services, dict):
        return False
    sso = services.get("sso")
    oauth2 = sso.get("oauth2") if isinstance(sso, dict) else None
    value = oauth2.get("pass_access_token") if isinstance(oauth2, dict) else None
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "on")
    return bool(value)


def _reading_roles() -> set[str]:
    """Return the roles that consume the header rather than emitting it.

    An nginx line that sets or strips the header names it too; only a line
    that does neither is a consumer reading the request.
    """
    prefix = str(ROLES_DIR) + "/"
    meta_name = ROLE_FILE_META_SERVICES.rsplit("/", 1)[-1]
    found: set[str] = set()
    for path, content in iter_project_files_with_content(
        extensions=tuple(_TEXT_SUFFIXES), exclude_tests=True
    ):
        if not path.startswith(prefix) or path.endswith(meta_name):
            continue
        for line in content.splitlines():
            if _HEADER_RE.search(line) and not _EMITS_RE.search(line):
                found.add(path[len(prefix) :].split("/", 1)[0])
                break
    return found


def _roles() -> list[Path]:
    return sorted(p for p in ROLES_DIR.iterdir() if p.is_dir())


class TestSsoAccessTokenOptIn(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.declared: set[str] = set()
        cls.suppressed: set[str] = set()
        for role in _roles():
            services, text = _load_services(role)
            if _declares_opt_in(services):
                cls.declared.add(role.name)
            if text and is_suppressed_in_head(text.splitlines(), _RULE):
                cls.suppressed.add(role.name)
        cls.readers = _reading_roles() - {"web-app-keycloak"}

    def test_every_reader_of_the_token_declares_the_opt_in(self) -> None:
        missing = sorted(self.readers - self.declared - self.suppressed)
        self.assertEqual(
            [],
            missing,
            "role(s) reading X-Forwarded-Access-Token without "
            "`services.sso.oauth2.pass_access_token: true`, so the gate blanks "
            f"the header: {missing}",
        )

    def test_no_role_asks_for_a_token_it_never_reads(self) -> None:
        unused = sorted(self.declared - self.readers - self.suppressed)
        self.assertEqual(
            [],
            unused,
            "role(s) declaring `pass_access_token: true` with no reference to "
            f"the header: {unused}",
        )

    def test_the_scan_finds_the_known_reader(self) -> None:
        self.assertIn("web-app-n8n", self.readers)

    def test_the_gate_makes_the_header_conditional(self) -> None:
        content = read_text(str(GATE))
        self.assertIn("oauth2_pass_access_token", content)
        self.assertIn('proxy_set_header X-Forwarded-Access-Token         "";', content)


if __name__ == "__main__":
    unittest.main()
