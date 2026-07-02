"""Eager placeholder substitution for cached user dicts.

Ansible 2.19's TrustedAsTemplate gate leaves untagged Jinja silently
unrendered, so values like `lastname: "{{ ORGANIZATION }}"` reach
downstream tasks as their literal string. These helpers substitute a
small set of group-vars scalars into the merged users dict before the
templar render pass, so consumers always see resolved values.

Extend `_SCALAR_USER_PLACEHOLDERS` (or call sites) when new scalar
group-vars appear in `roles/user-*/meta/users.yml` fields like
`firstname`, `lastname`, or `description`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

# Group-vars scalars that the users cache embeds as `{{ VAR }}` placeholders.
_SCALAR_USER_PLACEHOLDERS: tuple[str, ...] = (
    "ORGANIZATION",
    "SOFTWARE_NAME",
)


def substitute_primary_domain_placeholder(
    users: dict[str, Any],
    variables: dict[str, Any],
    *,
    templar: Any,
) -> dict[str, Any]:
    raw = variables.get("DOMAIN_PRIMARY")
    if not raw:
        return users
    text = str(raw).strip()
    if not text:
        return users
    if "{{" in text or "{%" in text:
        from utils.templating.ansible import _templar_render_best_effort

        text = str(_templar_render_best_effort(templar, text, dict(variables))).strip()
    if "://" in text:
        parsed = urlparse(text)
        text = parsed.hostname or text
    text = text.split("/", 1)[0].split(":", 1)[0].strip()
    if not text or "{{" in text or "{%" in text:
        return users

    placeholder = "{{ DOMAIN_PRIMARY }}"

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            return value.replace(placeholder, text) if placeholder in value else value
        if isinstance(value, Mapping):
            return {k: _walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_walk(v) for v in value)
        return value

    return _walk(users)


def substitute_scalar_placeholders(
    users: dict[str, Any],
    variables: dict[str, Any],
    *,
    templar: Any,
) -> dict[str, Any]:
    from utils.templating.ansible import _templar_render_best_effort

    resolved: dict[str, str] = {}
    for var in _SCALAR_USER_PLACEHOLDERS:
        raw = variables.get(var)
        if raw is None:
            continue
        text = str(raw).strip()
        if not text:
            continue
        if "{{" in text or "{%" in text:
            text = str(
                _templar_render_best_effort(templar, text, dict(variables))
            ).strip()
            if "{{" in text or "{%" in text:
                continue
        resolved[f"{{{{ {var} }}}}"] = text
    if not resolved:
        return users

    def _walk(value: Any) -> Any:
        if isinstance(value, str):
            out = value
            for placeholder, replacement in resolved.items():
                if placeholder in out:
                    out = out.replace(placeholder, replacement)
            return out
        if isinstance(value, Mapping):
            return {k: _walk(v) for k, v in value.items()}
        if isinstance(value, list):
            return [_walk(v) for v in value]
        if isinstance(value, tuple):
            return tuple(_walk(v) for v in value)
        return value

    return _walk(users)
