"""Roles whose backend logs a user in from a proxy-set identity header.

``TRUSTED_IDENTITY_HEADERS`` names every header such a backend may trust.

Every scan skips docs, Playwright files and ``PLATFORM_ROLES``. A line that
blanks a header is no trust, and a file carrying ``# nocheck: header-trust`` in
its head is an exemption, not a hit.

``header_trust_roles(roles_dir)`` -> ``dict[str, list[str]]``
    roles_dir: the repository's ``roles`` directory.
    Returns role name -> sorted role-relative paths of the files that name a
    trusted header in any spelling (``X-Remote-User``, ``HTTP_X_REMOTE_USER``,
    ``$http_x_remote_user``).

``header_trust_headers(roles_dir)`` -> ``dict[str, list[str]]``
    roles_dir: the repository's ``roles`` directory.
    Returns role name -> sorted canonical names of the headers those files name.

``header_trust_exemptions(roles_dir)`` -> ``dict[str, list[tuple[str, str]]]``
    roles_dir: the repository's ``roles`` directory.
    Returns role name -> ``(role-relative path, stated reason)`` per file that
    names a trusted header and carries the head marker.

``header_trust_declarations(roles_dir)`` -> ``dict[str, object]``
    roles_dir: the repository's ``roles`` directory.
    Returns role name -> the ``sso.header_trust`` value of its
    ``meta/services.yml``, for every role that declares one.

``declaration_problems(roles_dir)`` -> ``list[str]``
    roles_dir: the repository's ``roles`` directory.
    Returns one line per detected role without a valid declaration and per
    declaration on a role the scan does not detect. A declaration holds exactly
    ``proxy_secret`` (``false``, or a ``credentials`` key of the role's
    ``meta/secrets.yml``) and ``switch`` (the expression that switches the trust
    on; every ``services.`` path it names resolves in ``meta/services.yml``).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head, marker_reason
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SECRETS, ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterator
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

DECLARATION_SERVICE = "sso"
DECLARATION_KEY = "header_trust"
DECLARATION_FIELDS: frozenset[str] = frozenset({"proxy_secret", "switch"})

_RULE = "header-trust"
_SKIPPED_PARTS = ("/files/playwright/", "/__pycache__/")
_SKIPPED_NAMES = frozenset({"playwright.env.j2"})
_BLANKING = re.compile(r"proxy_set_header\s+\S+\s+\"\"\s*;")
_CANONICAL: dict[str, str] = {
    spelling: header
    for header in TRUSTED_IDENTITY_HEADERS
    for spelling in (header.lower(), f"http_{header.lower().replace('-', '_')}")
}
_HEADER_RE = re.compile(
    r"(?<![\w-])(?:"
    + "|".join(re.escape(spelling) for spelling in _CANONICAL)
    + r")(?![\w-])",
    re.IGNORECASE,
)
_SERVICES_PATH = re.compile(r"\bservices\.([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)")


def named_headers(text: str) -> list[str]:
    """Return the canonical trusted headers *text* names outside blanking lines.

    Args:
        text: the content of one file.
    """
    return sorted(
        {
            _CANONICAL[match.group(0).lower()]
            for line in text.splitlines()
            if not _BLANKING.search(line)
            for match in _HEADER_RE.finditer(line)
        }
    )


def _scanned_files(roles_dir: Path) -> Iterator[tuple[str, str, str]]:
    """Yield ``(role, role-relative path, text)`` per file that names a header."""
    for role_dir in sorted(roles_dir.iterdir()):
        if not role_dir.is_dir() or role_dir.name in PLATFORM_ROLES:
            continue
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
            if named_headers(text):
                yield role_dir.name, rel, text


def _exemption_reason(text: str) -> str | None:
    lines = text.splitlines()
    if not is_suppressed_in_head(lines, _RULE):
        return None
    return next(
        (
            reason
            for line in lines
            if (reason := marker_reason(line, _RULE)) is not None
        ),
        "",
    )


def header_trust_roles(roles_dir: Path) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for role, rel, text in _scanned_files(roles_dir):
        if _exemption_reason(text) is None:
            found.setdefault(role, []).append(rel)
    return found


def header_trust_headers(roles_dir: Path) -> dict[str, list[str]]:
    found: dict[str, set[str]] = {}
    for role, _, text in _scanned_files(roles_dir):
        if _exemption_reason(text) is None:
            found.setdefault(role, set()).update(named_headers(text))
    return {role: sorted(headers) for role, headers in found.items()}


def header_trust_exemptions(roles_dir: Path) -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = {}
    for role, rel, text in _scanned_files(roles_dir):
        reason = _exemption_reason(text)
        if reason is not None:
            found.setdefault(role, []).append((rel, reason))
    return found


def header_trust_declarations(roles_dir: Path) -> dict[str, object]:
    found: dict[str, object] = {}
    for services_file in sorted(roles_dir.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        services = load_yaml_any(str(services_file))
        block = services.get(DECLARATION_SERVICE) if isinstance(services, dict) else None
        if isinstance(block, dict) and DECLARATION_KEY in block:
            found[services_file.parent.parent.name] = block[DECLARATION_KEY]
    return found


def _resolves(services: object, path: str) -> bool:
    node = services
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return True


def _declaration_shape_problems(roles_dir: Path, role: str, value: object) -> list[str]:
    where = f"{role}: {ROLE_FILE_META_SERVICES} {DECLARATION_SERVICE}.{DECLARATION_KEY}"
    if not isinstance(value, dict) or set(value) != DECLARATION_FIELDS:
        return [f"{where} must hold exactly {sorted(DECLARATION_FIELDS)}"]
    problems: list[str] = []
    secret = value["proxy_secret"]
    if secret is not False:
        secrets_file = roles_dir / role / ROLE_FILE_META_SECRETS
        secrets = load_yaml_any(str(secrets_file)) if secrets_file.is_file() else None
        credentials = secrets.get("credentials") if isinstance(secrets, dict) else None
        if not (
            isinstance(secret, str)
            and isinstance(credentials, dict)
            and secret in credentials
        ):
            problems.append(
                f"{where}.proxy_secret must be false or a credentials key of "
                f"{ROLE_FILE_META_SECRETS}, got {secret!r}"
            )
    switch = value["switch"]
    if not isinstance(switch, str) or not switch.strip():
        problems.append(f"{where}.switch must be a non-empty string")
        return problems
    services = load_yaml_any(str(roles_dir / role / ROLE_FILE_META_SERVICES))
    problems.extend(
        f"{where}.switch names services.{path}, which {ROLE_FILE_META_SERVICES} lacks"
        for path in _SERVICES_PATH.findall(switch)
        if not _resolves(services, path)
    )
    return problems


def declaration_problems(roles_dir: Path) -> list[str]:
    detected = header_trust_roles(roles_dir)
    declared = header_trust_declarations(roles_dir)
    problems = [
        f"{role}: trusts a header in {', '.join(files)} but declares no "
        f"{DECLARATION_SERVICE}.{DECLARATION_KEY} in {ROLE_FILE_META_SERVICES}"
        for role, files in sorted(detected.items())
        if role not in declared
    ]
    problems.extend(
        f"{role}: declares {DECLARATION_SERVICE}.{DECLARATION_KEY} but no file of "
        "the role names a trusted header, so the declaration is dead"
        for role in sorted(declared)
        if role not in detected
    )
    for role in sorted(set(declared) & set(detected)):
        problems.extend(_declaration_shape_problems(roles_dir, role, declared[role]))
    return problems
