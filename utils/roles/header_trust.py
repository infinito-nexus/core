"""Roles whose backend logs a user in from a proxy-set identity header.

``TRUSTED_IDENTITY_HEADERS`` names every header such a backend may trust and
openresty blanks before it sets its own. ``DETECTED_HEADERS`` adds
``X-Forwarded-Access-Token``, which oauth2-proxy sets and some backends decode;
the scan detects it, and ``identity_request_strips.conf.j2`` already blanks it.

Every scan skips docs, Playwright files and ``PLATFORM_ROLES``. A line that
blanks a header is no trust, and a file carrying ``# nocheck: header-trust`` in
its head is an exemption, not a hit. The scan runs once per process and
resolved ``roles_dir``, so a file edited after the first call stays unseen, as
it does for ``read_text``.

``header_trust_roles(roles_dir)`` -> ``dict[str, list[str]]``
    roles_dir: the repository's ``roles`` directory.
    Returns role name -> sorted role-relative paths of the files that name a
    trusted header in any spelling (``X-Remote-User``, ``HTTP_X_REMOTE_USER``,
    ``$http_x_remote_user`` and, for ``X-`` headers, ``X_REMOTE_USER``).

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
    Returns one line per detected role without a valid declaration, per
    declaration on a role the scan does not detect and per
    ``# nocheck: header-trust`` marker that states no reason. A declaration
    holds exactly ``proxy_secret`` (``false``, or a ``credentials`` key of the
    role's ``meta/secrets.yml``), ``switch`` (the expression that switches the
    trust on; only its ``services.`` paths are checked, each must resolve in
    ``meta/services.yml``) and ``files`` (the role-relative files that make the
    backend trust the header; each names a trusted header itself or a
    ``vars/main.yml`` variable whose value names one).
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from utils.annotations.suppress import is_suppressed_in_head, marker_reason
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import (
    ROLE_FILE_META_SECRETS,
    ROLE_FILE_META_SERVICES,
    ROLE_FILE_VARS_MAIN,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

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

DETECTED_HEADERS: tuple[str, ...] = (
    *TRUSTED_IDENTITY_HEADERS,
    "X-Forwarded-Access-Token",
)

PLATFORM_ROLES: frozenset[str] = frozenset(
    {"sys-svc-proxy", "web-app-keycloak", "test-e2e-playwright"}
)

DECLARATION_SERVICE = "sso"
DECLARATION_KEY = "header_trust"
DECLARATION_FIELDS: frozenset[str] = frozenset({"proxy_secret", "switch", "files"})

_RULE = "header-trust"
_SKIPPED_PARTS = ("/files/playwright/", "/__pycache__/")
_SKIPPED_NAMES = frozenset({"playwright.env.j2"})
_NON_TRUSTING_PARTS = ("/files/playwright/", "/test/", "/tests/")
_COMMENT_LINE = re.compile(r"^\s*(?:#|//|/\*|\*|\{#|<!--|;)")
_BLANKING = re.compile(r"proxy_set_header\s+\S+\s+\"\"\s*;")


def _spellings(header: str) -> tuple[str, ...]:
    """Returns the spellings that name *header*; the bare underscore form only
    for ``X-`` headers, since a bare ``remote_user`` would match nginx's own
    ``$remote_user`` variable.

    Args:
        header: the canonical header name.
    """
    lower = header.lower()
    underscored = lower.replace("-", "_")
    bare = (underscored,) if lower.startswith("x-") else ()
    return (lower, f"http_{underscored}", *bare)


_CANONICAL: dict[str, str] = {
    spelling: header for header in DETECTED_HEADERS for spelling in _spellings(header)
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


def _scanned_files(roles_dir: Path) -> Iterator[tuple[str, str, list[str], str]]:
    """Yield ``(role, role-relative path, headers, text)`` per file that names a header."""
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
            headers = named_headers(text)
            if headers:
                yield role_dir.name, rel, headers, text


_Hit = tuple[str, str, tuple[str, ...], str | None]


@lru_cache(maxsize=4)
def _scan(roles_dir: str) -> tuple[_Hit, ...]:
    """Returns ``(role, role-relative path, headers, exemption reason)`` per
    file that names a header.

    Args:
        roles_dir: the resolved ``roles`` directory.
    """
    return tuple(
        (role, rel, tuple(headers), _exemption_reason(text))
        for role, rel, headers, text in _scanned_files(Path(roles_dir))
    )


def _hits(roles_dir: Path) -> tuple[_Hit, ...]:
    return _scan(str(roles_dir.resolve()))


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
    for role, rel, _, reason in _hits(roles_dir):
        if reason is None:
            found.setdefault(role, []).append(rel)
    return found


def header_trust_headers(roles_dir: Path) -> dict[str, list[str]]:
    found: dict[str, set[str]] = {}
    for role, _, headers, reason in _hits(roles_dir):
        if reason is None:
            found.setdefault(role, set()).update(headers)
    return {role: sorted(headers) for role, headers in found.items()}


def header_trust_exemptions(roles_dir: Path) -> dict[str, list[tuple[str, str]]]:
    found: dict[str, list[tuple[str, str]]] = {}
    for role, rel, _, reason in _hits(roles_dir):
        if reason is not None:
            found.setdefault(role, []).append((rel, reason))
    return found


def header_trust_declarations(roles_dir: Path) -> dict[str, object]:
    found: dict[str, object] = {}
    for services_file in sorted(roles_dir.glob(f"*/{ROLE_FILE_META_SERVICES}")):
        services = load_yaml_any(str(services_file))
        block = (
            services.get(DECLARATION_SERVICE) if isinstance(services, dict) else None
        )
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


def _header_vars(role_dir: Path) -> set[str]:
    path = role_dir / ROLE_FILE_VARS_MAIN
    variables = load_yaml_any(str(path)) if path.is_file() else None
    if not isinstance(variables, dict):
        return set()
    return {name for name, value in variables.items() if named_headers(str(value))}


def _not_a_trusting_file(role_dir: Path, rel: str) -> str | None:
    path = (role_dir / rel).resolve()
    if role_dir.resolve() not in path.parents:
        return "lies outside the role"
    if path.suffix == ".md":
        return "is documentation"
    if (
        path.name in _SKIPPED_NAMES
        or path.name.startswith("test")
        or any(part in f"/{rel}" for part in _NON_TRUSTING_PARTS)
    ):
        return "is a test file"
    if not path.is_file():
        return "does not exist"
    return None


def _files_problems(roles_dir: Path, role: str, files: object, where: str) -> list[str]:
    if not (
        isinstance(files, list)
        and files
        and all(isinstance(rel, str) and rel for rel in files)
    ):
        return [f"{where}.files must be a non-empty list of role-relative paths"]
    role_dir = roles_dir / role
    header_vars = _header_vars(role_dir)
    problems: list[str] = []
    for rel in files:
        reason = _not_a_trusting_file(role_dir, rel)
        if reason is not None:
            problems.append(f"{where}.files names {rel}, which {reason}")
            continue
        text = read_text(str(role_dir / rel))
        if _exemption_reason(text) is not None:
            problems.append(
                f"{where}.files names {rel}, which carries # nocheck: {_RULE}"
            )
            continue
        code = "\n".join(
            line for line in text.splitlines() if not _COMMENT_LINE.match(line)
        )
        if not named_headers(code) and not any(
            re.search(rf"\b{re.escape(name)}\b", code) for name in header_vars
        ):
            problems.append(
                f"{where}.files names {rel}, which names no trusted header and no "
                f"{ROLE_FILE_VARS_MAIN} variable holding one outside its comments"
            )
    return problems


def _declaration_shape_problems(roles_dir: Path, role: str, value: object) -> list[str]:
    where = f"{role}: {ROLE_FILE_META_SERVICES} {DECLARATION_SERVICE}.{DECLARATION_KEY}"
    if not isinstance(value, dict) or set(value) != DECLARATION_FIELDS:
        return [f"{where} must hold exactly {sorted(DECLARATION_FIELDS)}"]
    problems = _files_problems(roles_dir, role, value["files"], where)
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
    problems.extend(
        f"{role}: {rel} carries # nocheck: {_RULE} without a reason"
        for role, entries in sorted(header_trust_exemptions(roles_dir).items())
        for rel, reason in entries
        if not reason.strip()
    )
    return problems
