"""Deploy-log drift report of the ``enforced`` fields of ``meta/forms.yml``:
which overwrites a run names, and whether a line may show the old and new values.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from utils.roles.applications.forms import (
    _PATH,
    SourceError,
    _holds_template,
    _plain_field,
    _walk,
    iter_fields,
)

URL_USERINFO = re.compile(r"[a-z][a-z0-9+.-]*://[^/?#\s]*@", re.IGNORECASE)
PLAIN_VALUE_TYPES = (str, int, float, bool, type(None))


def secret_values(applications: Mapping, users: Mapping) -> frozenset[str]:
    """Collect the values the drift report must never show or contain.

    Args:
        applications: every resolved application by id, the reporting role's
            own included; every string leaf under the ``credentials`` and
            ``secrets.credentials`` of each one counts, so a credential of
            another role copied into a harmless field stays hidden.
        users: the resolved global users; every ``users.<key>.password`` counts.

    Returns:
        The non-empty secret strings, for an in-memory comparison only.
    """
    found: set[str] = set()
    for application in applications.values():
        if isinstance(application, Mapping):
            secrets = application.get("secrets")
            found |= _string_leaves(application.get("credentials"))
            if isinstance(secrets, Mapping):
                found |= _string_leaves(secrets.get("credentials"))
    for user in users.values():
        password = user.get("password") if isinstance(user, Mapping) else None
        if isinstance(password, str):
            found.add(password)
    return frozenset(value for value in found if value)


def _string_leaves(node: Any) -> set[str]:
    if isinstance(node, str):
        return {node}
    if isinstance(node, Mapping):
        return set().union(*(_string_leaves(child) for child in node.values()))
    if isinstance(node, list):
        return set().union(*(_string_leaves(child) for child in node))
    return set()


def _raw_value(raw_application: Mapping, source: Any) -> tuple[bool, Any]:
    if not (isinstance(source, str) and _PATH.fullmatch(source)):
        return False, None
    try:
        return True, _walk(raw_application, source.split("."), source)
    except SourceError:
        return False, None


def _value_reveals(value: Any, secrets: frozenset[str]) -> bool:
    text = str(value)
    return bool(URL_USERINFO.search(text)) or any(secret in text for secret in secrets)


def _shows_values(
    spec: Mapping,
    old: Any,
    new: Any,
    credentials: Mapping,
    raw: tuple[bool, Any],
    secrets: frozenset[str] | None,
) -> bool:
    resolved, raw_value = raw
    return (
        _plain_field(spec, credentials)
        and type(old) in PLAIN_VALUE_TYPES
        and type(new) in PLAIN_VALUE_TYPES
        and resolved
        and type(raw_value) in PLAIN_VALUE_TYPES
        and not _holds_template(raw_value)
        and secrets is not None
        and not _value_reveals(old, secrets)
        and not _value_reveals(new, secrets)
    )


def drift(
    role: str,
    forms: Mapping,
    desired: Mapping[str, Any],
    current: Mapping[str, Any],
    credentials: Mapping,
    *,
    raw_application: Mapping | None = None,
    secrets: frozenset[str] | None = None,
) -> list[str]:
    """Return one deploy-log line per enforced field the run is about to overwrite.

    Args:
        role: role name, used in the lines.
        forms: ``applications.<role>.forms``.
        desired: ``"<form>.<field>"`` mapped to the value its source resolves to.
        current: ``"<form>.<field>"`` mapped to the value the application holds;
            a field missing here was not read and is not reported. Values are
            shown only as plain ``str``, ``int``, ``float``, ``bool`` or
            ``None``; any other type, a ``str`` subclass included, is reported
            without values.
        credentials: the ``credentials`` tree of the role's ``meta/secrets.yml``.
        raw_application: the unrendered ``applications.<role>``, defaults and
            inventory overrides merged; without it no value and no source is
            shown.
        secrets: ``secret_values`` of every application; without it no value
            is shown.

    Returns:
        ``<role>: <form>.<field> (<source>): <old> -> <new>`` for a field the
        fail-closed rule of ``_shows_values`` lets show its values, and
        ``<role>: <form>.<field> (<source>): changed`` without either value for
        every other field. ``(<source>)`` appears only when the source resolved
        in ``raw_application``.
    """
    lines = []
    for form, field, spec in iter_fields(forms):
        key = f"{form}.{field}"
        if spec.get("mode") != "enforced" or key not in desired or key not in current:
            continue
        old, new = current[key], desired[key]
        if old == new:
            continue
        raw = (
            _raw_value(raw_application, spec.get("source"))
            if raw_application is not None
            else (False, None)
        )
        label = f"{key} ({spec['source']})" if raw[0] else key
        if _shows_values(spec, old, new, credentials, raw, secrets):
            lines.append(f"{role}: {label}: {old!r} -> {new!r}")
        else:
            lines.append(f"{role}: {label}: changed")
    return lines
