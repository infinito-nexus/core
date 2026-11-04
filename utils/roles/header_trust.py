"""Roles whose backend logs a user in from a proxy-set identity header.

``TRUSTED_IDENTITY_HEADERS`` names every header such a backend may trust.

``header_trust_roles(roles_dir)`` -> ``dict[str, list[str]]``
    roles_dir: the repository's ``roles`` directory.
    Returns role name -> sorted role-relative paths of the files that name a
    trusted header in any spelling (``X-Remote-User``, ``HTTP_X_REMOTE_USER``,
    ``$http_x_remote_user``). Docs, Playwright files, lines that blank a header,
    files carrying ``# nocheck: header-trust`` in their head and
    ``PLATFORM_ROLES`` are skipped.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head
from utils.cache.files import read_text

if TYPE_CHECKING:
    from pathlib import Path

TRUSTED_IDENTITY_HEADERS: tuple[str, ...] = (
    "X-Forwarded-User",
    "X-Forwarded-Preferred-Username",
    "X-Forwarded-Email",
    "X-Forwarded-Groups",
    "X-Auth-Request-User",
    "X-Auth-Request-Preferred-Username",
    "X-Auth-Request-Email",
    "X-Auth-Request-Groups",
    "Remote-User",
    "Remote-Email",
    "Remote-Groups",
    "X-Remote-User",
)

PLATFORM_ROLES: frozenset[str] = frozenset(
    {"sys-svc-proxy", "web-app-keycloak", "test-e2e-playwright"}
)

_RULE = "header-trust"
_SKIPPED_PARTS = ("/files/playwright/", "/__pycache__/")
_SKIPPED_NAMES = frozenset({"playwright.env.j2"})
_BLANKING = re.compile(r"proxy_set_header\s+\S+\s+\"\"\s*;")
_HEADER_RE = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(
        f"{re.escape(header.lower())}|http_{re.escape(header.lower().replace('-', '_'))}"
        for header in TRUSTED_IDENTITY_HEADERS
    )
    + r")(?![\w-])",
    re.IGNORECASE,
)


def _names_a_trusted_header(text: str) -> bool:
    return any(
        _HEADER_RE.search(line) and not _BLANKING.search(line)
        for line in text.splitlines()
    )


def header_trust_roles(roles_dir: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir() or role_dir.name in PLATFORM_ROLES:
            continue
        hits: list[str] = []
        for path in sorted(role_dir.rglob("*")):
            rel = path.relative_to(role_dir).as_posix()
            if not path.is_file() or path.suffix == ".md":
                continue
            if path.name in _SKIPPED_NAMES or any(
                part in f"/{rel}" for part in _SKIPPED_PARTS
            ):
                continue
            try:
                text = read_text(str(path))
            except (OSError, UnicodeDecodeError):
                continue
            if _names_a_trusted_header(text) and not is_suppressed_in_head(
                text.splitlines(), _RULE
            ):
                hits.append(rel)
        if hits:
            found[role_dir.name] = hits
    return found
