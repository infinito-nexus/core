"""Tor egress routing: the path every destination takes, and what that renders.

``services.tor.egress`` names a ``route`` for every destination no list matches
(``none``, ``onion``, ``all``) and two lists, ``tor`` and ``direct``, each an
``include`` with its own ``except``. An entry is a host name, a host name behind
a leading ``*.``, an IP address or a CIDR.

A host-name entry covers the name and every name below it. dnsmasq, which
carries the decision onto the wire, matches on label boundaries the same way
and has no form for one host without its subdomains, so ``example.org`` and
``*.example.org`` are the same entry. A narrower meaning here would promise an
exactness the resolver cannot keep.

Precedence, per destination:

1. ``except`` removes a match from its own ``include``.
2. A destination left in both lists takes Tor.
3. A destination left in neither takes the route: ``none`` direct, ``onion``
   direct except ``.onion``, ``all`` Tor.

Excepts cross kinds in one direction only. An address in ``direct.except`` also
removes the addresses that ``direct`` names resolve to, because nft checks it
before both direct sets; a name except never removes an address include. The
path follows the name a client asks for, so a direct name whose CNAME points at
a tor-listed name still goes direct.

Every host-name entry becomes a dnsmasq rule unless the rule above it already
gives the same path. dnsmasq picks the longest matching domain, and the entries
covering any name are exactly the entries covering its deepest covering entry,
so deciding each entry once decides every name below it.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from utils.networks import reachability

ROUTE_NONE = "none"
ROUTE_ONION = "onion"
ROUTE_ALL = "all"
ROUTES: tuple[str, ...] = (ROUTE_NONE, ROUTE_ONION, ROUTE_ALL)

TOR = "tor"
DIRECT = "direct"
LISTS: tuple[str, ...] = (TOR, DIRECT)
INCLUDE = "include"
EXCEPT = "except"
PARTS: tuple[str, ...] = (INCLUDE, EXCEPT)

ONION_DOMAIN = reachability.network(reachability.TOR).suffix.removeprefix(".")
WILDCARD_PREFIX = "*."
SET_NAMES: tuple[str, ...] = (
    "tor_v4",
    "tor_v6",
    "direct_v4",
    "direct_v6",
    "direct_except_v4",
    "direct_except_v6",
)
INFRASTRUCTURE = "infrastructure"
INFRASTRUCTURE_KEYS: tuple[str, ...] = ("mirrors", "ntp", "registry_blob_hosts", "acme")
EGRESS_KEYS: tuple[str, ...] = ("route", TOR, DIRECT, INFRASTRUCTURE)
REMOVED_KEY = "enabled"

_LABEL = re.compile(r"^(?!-)[a-z0-9_-]{1,63}(?<!-)$")

Network = ipaddress.IPv4Network | ipaddress.IPv6Network


@dataclass(frozen=True)
class Entry:
    """One parsed list entry.

    Args:
        raw: the entry as the operator wrote it.
        domain: the covered domain for a host-name entry, else None.
        network: the covered network for an address or CIDR entry, else None.
    """

    raw: str
    domain: str | None
    network: Network | None


def parse_entry(raw: Any) -> Entry:
    """Parse one entry, or raise ValueError naming what is wrong with it.

    Args:
        raw: a host name, ``*.`` host name, IP address or CIDR.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{raw!r} is not a host name, address or CIDR")
    text = raw.strip()
    try:
        return Entry(
            raw=text, domain=None, network=ipaddress.ip_network(text, strict=True)
        )
    except ValueError:
        pass
    try:
        loose = ipaddress.ip_network(text, strict=False)
    except ValueError:
        loose = None
    if loose is not None:
        raise ValueError(f"{text!r} has host bits set; write the network as {loose}")
    name = text.lower().rstrip(".").removeprefix(WILDCARD_PREFIX)
    labels = name.split(".")
    if not name or not all(_LABEL.match(label) for label in labels):
        raise ValueError(
            f"{text!r} is not a host name, address or CIDR; a wildcard is only "
            "allowed as one leading '*.' label"
        )
    if labels[-1].isdigit():
        raise ValueError(
            f"{text!r} is neither a valid address nor a host name: a top-level "
            "label cannot be all digits"
        )
    return Entry(raw=text, domain=name, network=None)


def covers(domain: str, name: str) -> bool:
    """Whether a host-name entry for *domain* covers *name*."""
    return name == domain or name.endswith("." + domain)


def is_onion(name: str) -> bool:
    return covers(ONION_DOMAIN, name)


def _block(egress: Mapping[str, Any], list_name: str, part: str) -> list[Any]:
    block = egress.get(list_name)
    if not isinstance(block, Mapping):
        raise TypeError(f"egress.{list_name} must be a mapping with include and except")
    value = block.get(part)
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"egress.{list_name}.{part} must be a list, got {value!r}")
    return list(value)


def parse_lists(egress: Mapping[str, Any]) -> dict[str, dict[str, list[Entry]]]:
    """Parse both lists, raising TypeError on a misshapen block and ValueError on
    the first malformed entry.

    Args:
        egress: a mapping carrying ``tor`` and ``direct``, each with ``include``
            and ``except`` lists.
    """
    return {
        list_name: {
            part: [parse_entry(raw) for raw in _block(egress, list_name, part)]
            for part in PARTS
        }
        for list_name in LISTS
    }


def _host_listed(lists: Mapping, list_name: str, name: str) -> bool:
    block = lists[list_name]
    included = any(
        e.domain is not None and covers(e.domain, name) for e in block[INCLUDE]
    )
    excepted = any(
        e.domain is not None and covers(e.domain, name) for e in block[EXCEPT]
    )
    return included and not excepted


def _address_listed(
    lists: Mapping,
    list_name: str,
    address: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    def hit(entries: Iterable[Entry]) -> bool:
        return any(
            e.network is not None
            and e.network.version == address.version
            and address in e.network
            for e in entries
        )

    block = lists[list_name]
    return hit(block[INCLUDE]) and not hit(block[EXCEPT])


def route_default(route: str, name: str) -> str:
    """The path a host name takes when no list matches it."""
    if route == ROUTE_ALL:
        return TOR
    if route == ROUTE_ONION and is_onion(name):
        return TOR
    return DIRECT


def host_path(route: str, lists: Mapping, name: str) -> str:
    """The path a host name takes.

    Args:
        route: one of ROUTES.
        lists: the result of parse_lists.
        name: the host name, in any case and with or without a trailing dot.
    """
    name = name.lower().rstrip(".")
    if _host_listed(lists, TOR, name):
        return TOR
    if _host_listed(lists, DIRECT, name):
        return DIRECT
    return route_default(route, name)


def address_path(route: str, lists: Mapping, address: str) -> str:
    """The path a literal IP address takes.

    Args:
        route: one of ROUTES.
        lists: the result of parse_lists.
        address: an IPv4 or IPv6 address.
    """
    parsed = ipaddress.ip_address(address)
    if _address_listed(lists, TOR, parsed):
        return TOR
    if _address_listed(lists, DIRECT, parsed):
        return DIRECT
    return TOR if route == ROUTE_ALL else DIRECT


def dns_rules(route: str, lists: Mapping) -> list[dict[str, str]]:
    """One rule per host-name entry whose path differs from the rule above it.

    Args:
        route: one of ROUTES.
        lists: the result of parse_lists.
    """
    domains = sorted(
        {
            e.domain
            for list_name in LISTS
            for part in PARTS
            for e in lists[list_name][part]
            if e.domain is not None
        }
    )
    rules = []
    for domain in domains:
        parents = [
            other for other in domains if other != domain and covers(other, domain)
        ]
        context = (
            host_path(route, lists, max(parents, key=len))
            if parents
            else route_default(route, domain)
        )
        path = host_path(route, lists, domain)
        if path != context:
            rules.append({"domain": domain, "path": path})
    return rules


def _subtract(includes: list[Network], excepts: list[Network]) -> list[Network]:
    remaining = list(includes)
    for excluded in excepts:
        kept: list[Network] = []
        for network in remaining:
            if network.version != excluded.version or not network.overlaps(excluded):
                kept.append(network)
            elif excluded.subnet_of(network) and excluded != network:
                kept.extend(network.address_exclude(excluded))
        remaining = kept
    return remaining


def _element(network: Network) -> str:
    if network.prefixlen == network.max_prefixlen:
        return str(network.network_address)
    return str(network)


def literal_sets(lists: Mapping) -> dict[str, list[str]]:
    """The address entries of each list after its excepts, per family.

    Args:
        lists: the result of parse_lists.
    """
    sets: dict[str, list[str]] = {}
    for list_name in LISTS:
        block = lists[list_name]
        effective = _subtract(
            [e.network for e in block[INCLUDE] if e.network is not None],
            [e.network for e in block[EXCEPT] if e.network is not None],
        )
        for version in (4, 6):
            collapsed = ipaddress.collapse_addresses(
                n for n in effective if n.version == version
            )
            sets[f"{list_name}_v{version}"] = [_element(n) for n in collapsed]
    excepted = [e.network for e in lists[DIRECT][EXCEPT] if e.network is not None]
    for version in (4, 6):
        collapsed = ipaddress.collapse_addresses(
            n for n in excepted if n.version == version
        )
        sets[f"direct_except_v{version}"] = [_element(n) for n in collapsed]
    return sets


def admitted(addresses: Iterable[str], cidrs: Iterable[str]) -> list[str]:
    """The addresses that fall inside any of *cidrs*.

    Args:
        addresses: IP addresses, e.g. the clearnet resolvers dnsmasq forwards to.
        cidrs: networks or single addresses, e.g. the resolver set the DNS
            guard admits for every process.
    """
    networks = [ipaddress.ip_network(str(cidr), strict=False) for cidr in cidrs]
    found = []
    for address in addresses:
        parsed = ipaddress.ip_address(str(address).strip())
        if any(parsed.version == n.version and parsed in n for n in networks):
            found.append(str(address))
    return found


def role_subnets(
    applications: Mapping[str, Any], group_names: Iterable[str]
) -> list[str]:
    """The local subnet of every deployed application that declares one.

    Args:
        applications: the merged applications mapping.
        group_names: the application ids deployed on this host.
    """
    subnets = []
    for application_id in group_names:
        config = applications.get(application_id)
        networks = config.get("networks") if isinstance(config, Mapping) else None
        local = networks.get("local") if isinstance(networks, Mapping) else None
        subnet = local.get("subnet") if isinstance(local, Mapping) else None
        if isinstance(subnet, str) and subnet.strip():
            subnets.append(subnet.strip())
    return sorted(set(subnets))


def plan(egress: Mapping[str, Any], route: str) -> dict[str, Any]:
    """Everything the templates render for one route and its lists.

    Args:
        egress: a mapping carrying the ``tor`` and ``direct`` lists.
        route: one of ROUTES.

    Returns:
        ``dns``: dnsmasq rules, each ``{"domain", "path"}``;
        ``sets``: nft set elements keyed by SET_NAMES;
        ``tor_listed``: whether the tor list carries any address;
        ``direct_names``: whether any rule sends a name the direct way;
        ``automap_all``: whether a clearnet name reaches Tor's DNSPort, so
        Tor must hand out virtual addresses for every suffix.
    """
    if route not in ROUTES:
        raise ValueError(
            f"egress.route must be one of {', '.join(ROUTES)}, got {route!r}"
        )
    lists = parse_lists(egress)
    rules = dns_rules(route, lists)
    sets = literal_sets(lists)
    return {
        "dns": rules,
        "sets": sets,
        "tor_listed": bool(sets["tor_v4"] or sets["tor_v6"]),
        "direct_names": any(rule["path"] == DIRECT for rule in rules),
        "automap_all": route == ROUTE_ALL
        or any(rule["path"] == TOR and not is_onion(rule["domain"]) for rule in rules),
    }


def _infrastructure_violations(declared: Any) -> list[str]:
    if not isinstance(declared, Mapping):
        return [
            f"egress.{INFRASTRUCTURE} must be a mapping with {', '.join(INFRASTRUCTURE_KEYS)}"
        ]
    found = []
    for key in INFRASTRUCTURE_KEYS:
        value = declared.get(key)
        expected = Mapping if key == "registry_blob_hosts" else (list, tuple)
        if not isinstance(value, expected):
            found.append(
                f"egress.{INFRASTRUCTURE}.{key} is missing or has the wrong type: {value!r}"
            )
    return found


def violations(egress: Mapping[str, Any], route: str, swarm: bool) -> list[str]:
    """Every reason the route and its lists cannot be deployed.

    Args:
        egress: a mapping carrying the ``tor`` and ``direct`` lists.
        route: one of ROUTES.
        swarm: whether the deploy runs in swarm mode.
    """
    found: list[str] = []
    if REMOVED_KEY in egress:
        found.append(
            "egress.enabled was replaced by egress.route; set route: onion where "
            "it was true and route: none where it was false, then drop enabled"
        )
    unknown = sorted(set(egress) - set(EGRESS_KEYS) - {REMOVED_KEY})
    if unknown:
        found.append(
            f"egress carries unknown keys {', '.join(unknown)}; allowed: {', '.join(EGRESS_KEYS)}"
        )
    found.extend(_infrastructure_violations(egress.get(INFRASTRUCTURE)))
    if route not in ROUTES:
        found.append(f"egress.route must be one of {', '.join(ROUTES)}, got {route!r}")
    try:
        lists = parse_lists(egress)
    except (TypeError, ValueError) as exc:
        return [*found, str(exc)]

    if route == ROUTE_NONE:
        filled = [
            f"{list_name}.{part}"
            for list_name in LISTS
            for part in PARTS
            if lists[list_name][part]
        ]
        if filled:
            found.append(
                "route none leaves egress untouched, so the lists must be empty; "
                f"non-empty: {', '.join(filled)}"
            )
    if route == ROUTE_ALL and swarm:
        found.append(
            "route all is not supported in swarm mode: the egress router runs on "
            "the managers only, so every worker would send its containers' "
            "traffic direct where route all must fail closed"
        )
    found.extend(
        f"{entry.raw!r} cannot be reached directly: .onion only exists inside Tor"
        for entry in lists[DIRECT][INCLUDE]
        if entry.domain is not None and is_onion(entry.domain)
    )
    return found


def literal_overlaps(egress: Mapping[str, Any]) -> list[str]:
    """Entries written into both includes; they take Tor.

    Args:
        egress: a mapping carrying the ``tor`` and ``direct`` lists.
    """
    lists = parse_lists(egress)

    def key(entry: Entry) -> str:
        return entry.domain if entry.domain is not None else str(entry.network)

    tor = {key(e): e.raw for e in lists[TOR][INCLUDE]}
    return sorted(
        raw for raw in (e.raw for e in lists[DIRECT][INCLUDE] if key(e) in tor)
    )
