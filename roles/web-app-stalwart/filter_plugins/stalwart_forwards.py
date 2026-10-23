from __future__ import annotations

import re
from typing import Any

from ansible.errors import AnsibleFilterError

_INCLUDE = re.compile(r'^include :personal "((?:[^"\\]|\\.)*)";$', re.MULTILINE)


def _is_address(value: str) -> bool:
    local, at, domain = value.rpartition("@")
    return bool(at and local and "@" not in local and "." in domain)


def _sieve_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')


def stalwart_forwards(forwards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalise the declared per-account forwards.

    Args:
        forwards: ``[{"address": ..., "destinations": [...]}]``; the account at
            ``address`` keeps its copy and every destination receives one.

    Returns:
        ``[{"address", "destinations"}]`` in lowercase.

    Raises:
        AnsibleFilterError: a malformed entry, a repeated address, or a
            destination equal to the forwarding account.
    """
    if not isinstance(forwards, list):
        raise AnsibleFilterError(
            f"stalwart forwards: a list is required, got {forwards!r}"
        )
    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in forwards:
        if not isinstance(entry, dict) or set(entry) != {"address", "destinations"}:
            raise AnsibleFilterError(
                f"stalwart forwards: entry {entry!r} needs exactly 'address' and 'destinations'"
            )
        address = str(entry["address"]).strip().lower()
        destinations = entry["destinations"]
        if (
            not _is_address(address)
            or not isinstance(destinations, list)
            or not destinations
        ):
            raise AnsibleFilterError(
                f"stalwart forwards: {entry!r} needs an address and a non-empty destinations list"
            )
        destinations = sorted({str(d).strip().lower() for d in destinations})
        if not all(_is_address(d) for d in destinations) or address in destinations:
            raise AnsibleFilterError(
                f"stalwart forwards: invalid destinations for {address}"
            )
        if address in seen:
            raise AnsibleFilterError(f"stalwart forwards: {address} is declared twice")
        seen.add(address)
        normalised.append({"address": address, "destinations": destinations})
    return normalised


def stalwart_forward_include(
    scripts: list[dict[str, Any]], own_name: str, own_content: str
) -> str:
    """Name the user script the forward script chains into.

    Args:
        scripts: the account's ``SieveScript/get`` list.
        own_name: name of the role's forward script.
        own_content: current text of the role's forward script, '' when absent.

    Returns:
        The active user script, else the one the forward script already
        includes, else '' when the account has no user script to keep.
    """
    names = {str(s["name"]) for s in scripts}
    active = next((s for s in scripts if s.get("isActive")), None)
    if active and active["name"] != own_name:
        return str(active["name"])
    match = _INCLUDE.search(own_content)
    if match:
        included = match.group(1).replace('\\"', '"').replace("\\\\", "\\")
        if included in names:
            return included
    return ""


def stalwart_forward_script(destinations: list[str], include: str) -> str:
    """Render the forward script.

    Args:
        destinations: addresses that each receive a copy.
        include: user script run after the redirects, '' for none.
    """
    extensions = '"copy", "include"' if include else '"copy"'
    lines = [f"require [{extensions}];"]
    lines += [f'redirect :copy "{_sieve_string(d)}";' for d in destinations]
    if include:
        lines.append(f'include :personal "{_sieve_string(include)}";')
    return "\n".join(lines) + "\n"


class FilterModule:
    def filters(self):
        return {
            "stalwart_forwards": stalwart_forwards,
            "stalwart_forward_include": stalwart_forward_include,
            "stalwart_forward_script": stalwart_forward_script,
        }
