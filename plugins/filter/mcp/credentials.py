from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def mcp_with_credentials(servers: Any, discovered: Any) -> list:
    """
    Args:
        servers: the public entries of a client's MCP form, as
            lookup('form_values', ...) converges them.
        discovered: MCP_DISCOVERED_SERVERS, the task-time discovery whose
            entries carry the credentials.

    Returns:
        Each managed entry in its order, with the keys only the discovered
        entry of the same id holds joined in, while every public key keeps
        the managed value; a managed entry the task-time discovery rejected,
        such as one whose credential is not written yet, is left out.
    """
    by_id = {str(entry.get("id")): entry for entry in discovered or []}
    return [
        {**by_id[str(server.get("id"))], **server}
        for server in servers or []
        if str(server.get("id")) in by_id
    ]


def _url(entry: Any) -> Any:
    return entry.get("url") if isinstance(entry, Mapping) else entry


def mcp_held(servers: Any, entries: Any, dash: str) -> list:
    """
    Args:
        servers: the public entries of a client's MCP form.
        entries: each server key the client holds, mapped to the URL it
            holds or to its entry, whose ``url`` is read.
        dash: what the client writes for each dash of a server id in its
            key.

    Returns:
        The client's servers in the shape of the form: each managed entry
        the client holds, with the URL it holds, followed by an entry of key
        and URL for each server the client holds that no managed entry names.
    """
    held = {str(key): _url(entry) for key, entry in dict(entries or {}).items()}
    keys = {
        str(server.get("id")).replace("-", dash): server for server in servers or []
    }
    found = [
        {**server, "url": held[key]} for key, server in keys.items() if key in held
    ]
    extra = [
        {"id": key, "url": url} for key, url in sorted(held.items()) if key not in keys
    ]
    return found + extra


class FilterModule:
    def filters(self):
        return {"mcp_with_credentials": mcp_with_credentials, "mcp_held": mcp_held}
