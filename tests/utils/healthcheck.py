from __future__ import annotations

import re
from typing import Any

TABLE_CHOICE = re.compile(
    r"""^\{\{\s*lookup\(\s*(['"])config\1\s*,\s*(['"])[^'"]+\2\s*,\s*(['"])services\.([a-z0-9_-]+)\.([a-z0-9_-]+)\3\s*\)\s*\[.+\]\s*\}\}$""",
    re.DOTALL,
)


def healthcheck_entries(
    services: dict[str, Any], key: str
) -> list[tuple[tuple[str, ...], Any]]:
    """Args:
        services: the application's ``services`` mapping.
        key: the service key.

    Returns:
        ``(path, entry)`` per healthcheck entry the service can render to, the
        path running from the top-level service key down to the entry. A
        ``{{ lookup('config', <app>, 'services.<owner>.<table>')[<selector>] }}``
        choice yields every entry of that table, which the config SPOT renders
        into the one entry its selector names; any other ``healthcheck`` value
        yields itself.
    """
    declared = services[key].get("healthcheck")
    choice = TABLE_CHOICE.match(declared) if isinstance(declared, str) else None
    owner = services.get(choice.group(4)) if choice else None
    table = owner.get(choice.group(5)) if isinstance(owner, dict) else None
    if not isinstance(table, dict) or not table:
        return [((key, "healthcheck"), declared)]
    return [
        ((choice.group(4), choice.group(5), str(name)), entry)
        for name, entry in table.items()
    ]


def declares_healthcheck(services: dict[str, Any], key: str) -> bool:
    """Args:
        services: the application's ``services`` mapping.
        key: the service key.

    Returns:
        Whether the service's ``healthcheck`` is, or selects, a mapping.
    """
    return any(
        isinstance(entry, dict) for _path, entry in healthcheck_entries(services, key)
    )
