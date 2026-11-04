from __future__ import annotations

import re
from typing import Any

from ansible.errors import AnsibleFilterError

_DOMAIN = re.compile(r"^[a-z0-9-]+(\.[a-z0-9-]+)+$")


def _domain(entry: dict[str, Any], key: str) -> str:
    value = str(entry.get(key) or "").strip().lower()
    if not _DOMAIN.match(value):
        raise AnsibleFilterError(
            f"stalwart alias_domains: '{key}' must be a domain, got {entry!r}"
        )
    return value


def stalwart_rcpt_rewrite(alias_domains: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the RCPT stage ``rewrite`` expression for the alias domains.

    Args:
        alias_domains: ``[{"source": <legacy domain>, "target": <domain>}]``;
            ``<local>@<source>`` is delivered to ``<local>@<target>``.

    Returns:
        The Stalwart expression ``{"match": {...}, "else": "false"}``, one
        match per alias domain in declaration order.

    Raises:
        AnsibleFilterError: a malformed entry, a repeated source, or a source
            equal to its target.
    """
    if not isinstance(alias_domains, list):
        raise AnsibleFilterError(
            f"stalwart alias_domains: a list is required, got {alias_domains!r}"
        )
    match: dict[str, dict[str, str]] = {}
    seen: set[str] = set()
    for entry in alias_domains:
        if not isinstance(entry, dict):
            raise AnsibleFilterError(
                f"stalwart alias_domains: an entry must be a mapping, got {entry!r}"
            )
        source = _domain(entry, "source")
        target = _domain(entry, "target")
        if source == target or source in seen:
            raise AnsibleFilterError(
                f"stalwart alias_domains: '{source}' is repeated or targets itself"
            )
        seen.add(source)
        pattern = "(?i)^([^@]+)@" + source.replace(".", "\\.") + "$"
        match[str(len(match))] = {
            "if": f"matches('{pattern}', rcpt)",
            "then": f"$1 + '@{target}'",
        }
    return {"match": match, "else": "false"}


class FilterModule:
    def filters(self):
        return {"stalwart_rcpt_rewrite": stalwart_rcpt_rewrite}
