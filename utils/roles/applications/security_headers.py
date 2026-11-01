"""Response security headers the front proxy adds for one application.

``WEBSERVER_SECURITY_HEADERS`` holds the platform values. An application
overrides any of them under ``security_headers`` in its ``meta/server.yml``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from utils.roles.applications.config import get

HSTS_PRELOAD_MIN_MAX_AGE = 31536000

REFERRER_POLICY_TOKENS = frozenset(
    {
        "no-referrer",
        "no-referrer-when-downgrade",
        "origin",
        "origin-when-cross-origin",
        "same-origin",
        "strict-origin",
        "strict-origin-when-cross-origin",
        "unsafe-url",
    }
)

SCHEMA: dict[str, Any] = {
    "nosniff": bool,
    "referrer_policy": str,
    "permissions_policy": str,
    "hsts": {
        "max_age": int,
        "include_subdomains": bool,
        "preload": bool,
    },
}

_FIELD_VALUE = re.compile(r"[\x20-\x7e]*")


def _check_type(value: Any, expected: type, where: str) -> None:
    if expected is int:
        valid = isinstance(value, int) and not isinstance(value, bool)
    else:
        valid = isinstance(value, expected)
    if not valid:
        raise TypeError(
            f"{where} must be {expected.__name__}, got {type(value).__name__} {value!r}"
        )


def _resolve(
    schema: Mapping[str, Any], base: Any, override: Any, where: str
) -> dict[str, Any]:
    """Validate *override* against *schema* and lay it over *base*.

    Args:
        schema: the expected keys and their types.
        base: the complete mapping the override applies to, ``None`` when
            *override* is the complete mapping itself.
        override: the mapping to validate; partial when *base* is given.
        where: dotted origin of *override*, for error messages.

    Returns:
        A complete mapping with every key of *schema*.
    """
    if not isinstance(override, Mapping):
        raise TypeError(f"{where} must be a mapping, got {override!r}")
    unknown = sorted(set(override) - set(schema))
    if unknown:
        raise ValueError(f"{where} has unknown keys {unknown}, known: {sorted(schema)}")
    if base is None:
        missing = sorted(set(schema) - set(override))
        if missing:
            raise ValueError(f"{where} lacks the keys {missing}")

    resolved: dict[str, Any] = {}
    for key, expected in schema.items():
        path = f"{where}.{key}"
        if key not in override:
            resolved[key] = base[key]
        elif isinstance(expected, Mapping):
            resolved[key] = _resolve(
                expected, None if base is None else base[key], override[key], path
            )
        else:
            _check_type(override[key], expected, path)
            resolved[key] = override[key]
    return resolved


def _field_value(value: str, where: str) -> str:
    if not _FIELD_VALUE.fullmatch(value):
        raise ValueError(f"{where} must be printable ASCII, got {value!r}")
    return value


def _referrer_policy(value: str, where: str) -> str:
    _field_value(value, where)
    if not value:
        return value
    unknown = [
        token
        for token in (part.strip() for part in value.split(","))
        if token not in REFERRER_POLICY_TOKENS
    ]
    if unknown:
        raise ValueError(f"{where} has unknown policy tokens {unknown}")
    return value


def _hsts(hsts: Mapping[str, Any], where: str) -> str:
    if hsts["max_age"] < 0:
        raise ValueError(f"{where}.max_age must not be negative")
    if hsts["preload"] and not hsts["include_subdomains"]:
        raise ValueError(f"{where}.preload requires include_subdomains")
    if hsts["preload"] and hsts["max_age"] < HSTS_PRELOAD_MIN_MAX_AGE:
        raise ValueError(
            f"{where}.preload requires a max_age of at least {HSTS_PRELOAD_MIN_MAX_AGE}"
        )
    directives = [f"max-age={hsts['max_age']}"]
    if hsts["include_subdomains"]:
        directives.append("includeSubDomains")
    if hsts["preload"]:
        directives.append("preload")
    return "; ".join(directives)


def security_headers(
    applications: Mapping[str, Any], application_id: str, platform: Mapping[str, Any]
) -> dict[str, Any]:
    """Return the security header values the proxy sends for *application_id*.

    Args:
        applications: the applications SPOT.
        application_id: the role whose vhost is rendered; a redirect vhost
            passes its domain, which owns no override.
        platform: ``WEBSERVER_SECURITY_HEADERS``.

    Returns:
        ``nosniff`` as a bool, ``referrer_policy`` and ``permissions_policy``
        as header values (empty when not sent) and ``hsts`` as the complete
        ``Strict-Transport-Security`` value.
    """
    base = _resolve(SCHEMA, None, platform, "WEBSERVER_SECURITY_HEADERS")
    where = f"applications[{application_id!r}].server.security_headers"
    override = get(
        applications,
        application_id,
        "server.security_headers",
        strict=False,
        default={},
        skip_missing_app=True,
    )
    resolved = _resolve(SCHEMA, base, override, where)
    return {
        "nosniff": resolved["nosniff"],
        "referrer_policy": _referrer_policy(
            resolved["referrer_policy"], f"{where}.referrer_policy"
        ),
        "permissions_policy": _field_value(
            resolved["permissions_policy"], f"{where}.permissions_policy"
        ),
        "hsts": _hsts(resolved["hsts"], f"{where}.hsts"),
    }
