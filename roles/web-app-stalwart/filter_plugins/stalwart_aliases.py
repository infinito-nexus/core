from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleFilterError

CATCH_ALL_LOCAL = ""


def _split(address: str, where: str) -> tuple[str, str]:
    local, at, domain = address.rpartition("@")
    if not at or not domain or "." not in domain or "@" in local:
        raise AnsibleFilterError(
            f"stalwart aliases: invalid address {address!r} in {where}"
        )
    return local, domain


def stalwart_aliases(aliases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and normalise the declared aliases.

    Args:
        aliases: ``[{"address": ..., "destinations": [...]}]``; the address
            ``@<domain>`` declares the catch-all of that domain.

    Returns:
        ``[{"address", "local", "domain", "destinations"}]`` in lowercase.

    Raises:
        AnsibleFilterError: a malformed entry, a repeated address, or a
            catch-all with other than exactly one destination.
    """
    if not isinstance(aliases, list):
        raise AnsibleFilterError(
            f"stalwart aliases: a list is required, got {aliases!r}"
        )
    normalised: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entry in aliases:
        if not isinstance(entry, dict) or set(entry) != {"address", "destinations"}:
            raise AnsibleFilterError(
                f"stalwart aliases: entry {entry!r} needs exactly 'address' and 'destinations'"
            )
        address = str(entry["address"]).strip().lower()
        local, domain = _split(address, "address")
        destinations = entry["destinations"]
        if not isinstance(destinations, list) or not destinations:
            raise AnsibleFilterError(
                f"stalwart aliases: {address} needs a non-empty destinations list"
            )
        destinations = [str(d).strip().lower() for d in destinations]
        for destination in destinations:
            if _split(destination, address)[0] == CATCH_ALL_LOCAL:
                raise AnsibleFilterError(
                    f"stalwart aliases: {address} names a catch-all as a destination"
                )
        if local == CATCH_ALL_LOCAL and len(destinations) != 1:
            raise AnsibleFilterError(
                f"stalwart aliases: catch-all {address} takes exactly one destination"
            )
        if address in seen:
            raise AnsibleFilterError(f"stalwart aliases: {address} is declared twice")
        seen.add(address)
        normalised.append(
            {
                "address": address,
                "local": local,
                "domain": domain,
                "destinations": sorted(set(destinations)),
            }
        )
    return normalised


def stalwart_alias_plan(
    aliases: list[dict[str, Any]],
    domains: list[dict[str, Any]],
    lists: list[dict[str, Any]],
    marker: str,
) -> dict[str, Any]:
    """Diff the declared aliases against the live Stalwart objects.

    Args:
        aliases: output of ``stalwart_aliases``.
        domains: the ``x:Domain/get`` list.
        lists: the ``x:MailingList/get`` list.
        marker: description that tags the mailing lists this role created.

    Returns:
        ``create``/``update``/``destroy`` for ``x:MailingList/set`` and
        ``domains``, the ``update`` of ``x:Domain/set`` for the catch-alls.

    Raises:
        AnsibleFilterError: an alias in a domain Stalwart does not serve, or an
            alias address held by a mailing list the role did not create.
    """
    domain_ids = {str(d["name"]).lower(): d["id"] for d in domains}
    live_catch_all = {d["id"]: d.get("catchAllAddress") for d in domains}
    unserved = sorted({a["domain"] for a in aliases} - set(domain_ids))
    if unserved:
        raise AnsibleFilterError(
            f"stalwart aliases: Stalwart does not serve the alias domains {unserved}"
        )
    live = {(str(item["name"]).lower(), item["domainId"]): item for item in lists}
    plan: dict[str, Any] = {"create": {}, "update": {}, "destroy": [], "domains": {}}
    declared: set[tuple[str, str]] = set()
    for alias in aliases:
        domain_id = domain_ids[alias["domain"]]
        if alias["local"] == CATCH_ALL_LOCAL:
            if live_catch_all.get(domain_id) != alias["destinations"][0]:
                plan["domains"][domain_id] = {
                    "catchAllAddress": alias["destinations"][0]
                }
            continue
        key = (alias["local"], domain_id)
        declared.add(key)
        recipients = dict.fromkeys(alias["destinations"], True)
        current = live.get(key)
        if current is None:
            plan["create"][f"a{len(plan['create'])}"] = {
                "name": alias["local"],
                "domainId": domain_id,
                "description": marker,
                "recipients": recipients,
            }
        elif current.get("description") != marker:
            raise AnsibleFilterError(
                f"stalwart aliases: {alias['address']} is a mailing list this role did not create"
            )
        elif set(current.get("recipients") or {}) != set(recipients):
            plan["update"][current["id"]] = {"recipients": recipients}
    plan["destroy"] = sorted(
        item["id"]
        for key, item in live.items()
        if item.get("description") == marker and key not in declared
    )
    return plan


class FilterModule:
    def filters(self):
        return {
            "stalwart_aliases": stalwart_aliases,
            "stalwart_alias_plan": stalwart_alias_plan,
        }
