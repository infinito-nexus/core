"""HTTP status codes for a deployed domain.

``roles/<app>/meta/server.yml`` declares ``status_codes`` keyed like
``domains.canonical``; it is the single source of truth for every prober.
"""

from __future__ import annotations

from collections.abc import Mapping

from utils.roles.applications.config import get

DEFAULT_OK = [200, 302, 301]


def normalize_codes(value) -> list[int]:
    """Return *value* as a list of plausible HTTP status codes.

    Args:
        value: a scalar, list or mapping straight out of the declaration.

    Returns:
        The codes as de-duplicated integers, dropping anything outside 100-599.
    """
    if value is None:
        return []
    candidates = value if isinstance(value, (list, tuple, set)) else [value]
    codes: list[int] = []
    for candidate in candidates:
        if isinstance(candidate, bool):
            continue
        try:
            code = int(candidate)
        except (TypeError, ValueError):
            continue
        if 100 <= code <= 599 and code not in codes:
            codes.append(code)
    return codes


def codes_by_key(raw) -> dict[str, list[int]]:
    """Normalize a raw ``server.status_codes`` declaration.

    Args:
        raw: the declaration as read from the app config.

    Returns:
        The declared keys mapped to their codes, dropping keys that declare
        nothing usable.
    """
    if not isinstance(raw, Mapping):
        return {}
    resolved: dict[str, list[int]] = {}
    for key, value in raw.items():
        codes = normalize_codes(value)
        if codes:
            resolved[str(key)] = codes
    return resolved


def declared_status_codes(applications, app_id: str, domain: str) -> list[int]:
    """Return what *app_id* declares for *domain*, or an empty list.

    The vhost is identified by the ``domains.canonical`` key that carries the
    domain, which is the same key ``server.status_codes`` uses. A domain that
    is not canonical, or a key that declares nothing, falls back to the
    declared ``default``.

    Args:
        applications: the applications SPOT.
        app_id: the role the domain belongs to.
        domain: the fully qualified domain being probed.

    Returns:
        The declared codes, empty when the app declares none for this domain.
    """
    declared = codes_by_key(
        get(applications, app_id, "server.status_codes", strict=False, default={})
    )
    if not declared:
        return []

    wanted = str(domain or "").strip()
    canonical = get(applications, app_id, "domains.canonical", strict=False, default=[])
    if wanted and isinstance(canonical, Mapping):
        for key, domains in canonical.items():
            entries = domains if isinstance(domains, (list, tuple, set)) else [domains]
            if wanted in {str(entry).strip() for entry in entries if entry}:
                codes = declared.get(str(key))
                if codes:
                    return list(codes)
                break

    return list(declared.get("default") or [])


def accepted_status_codes(applications, app_id: str, domain: str) -> list[int]:
    """Return the codes that prove *domain* is being served at all.

    Most declarations are narrower than :data:`DEFAULT_OK`, so this gate adds
    to the default instead of replacing it; narrowing it would escalate vhosts
    that answer perfectly well. Contract checking is a different question and
    belongs to ``sys-ctl-hlth-webserver``.

    Args:
        applications: the applications SPOT.
        app_id: the role the domain belongs to.
        domain: the fully qualified domain being probed.

    Returns:
        :data:`DEFAULT_OK` plus whatever the app declares for this domain.
    """
    accepted = list(DEFAULT_OK)
    accepted.extend(
        code
        for code in declared_status_codes(applications, app_id, domain)
        if code not in accepted
    )
    return accepted
