"""The vhost domains one logical domain is served under on this host."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.reachability import (
    NETWORKS,
    TOR,
    network,
    sibling_domain,
    tor_serves_host,
)
from utils.tls.common import iter_domains, norm_domain

if TYPE_CHECKING:
    from collections.abc import Callable


def network_family(
    domain: str, domains: dict[str, Any], primary: str, node: str
) -> list[str]:
    """Return every vhost domain the logical domain of ``domain`` is served under.

    Args:
        domain: any network sibling of the logical domain.
        domains: the host's merged domain map.
        primary: the node's ``DOMAIN_PRIMARY``.
        node: the node onion address, empty without Tor.

    Returns:
        One domain per network the owning app is served on, canonical network
        first, whichever sibling ``domain`` names; ``[domain]`` for a domain
        the map does not know.
    """
    host = norm_domain(domain)
    variants = [
        variant
        for name in NETWORKS
        if (variant := sibling_domain(host, name, primary, node))
    ]
    for value in domains.values():
        served = [norm_domain(d) for d in iter_domains(value)]
        found = [variant for variant in variants if variant in served]
        if found:
            return found
    return [host]


def served_siblings(
    domain: str, domains: dict[str, Any], primary: str, node: str
) -> list[str]:
    """Return the vhost domains ``domain`` is served under.

    Args:
        domain: the domain a role asks to front.
        domains: the host's merged domain map.
        primary: the node's ``DOMAIN_PRIMARY``.
        node: the node onion address, empty without Tor.

    Returns:
        One domain per network the owning app is served on, canonical network
        first; ``[]`` for a non-canonical sibling whose canonical twin renders
        it; ``[domain]`` for a domain the map does not know.
    """
    family = network_family(domain, domains, primary, node)
    host = norm_domain(domain)
    return [] if host in family and host != family[0] else family


def sibling_scope(
    variables: dict[str, Any], run: Callable[..., Any], templar: Any
) -> tuple[dict[str, Any], str, str]:
    """Return what the network siblings of a domain resolve against on this host.

    Args:
        variables: lookup scope carrying ``DOMAIN_PRIMARY``, ``group_names``
            and ``groups``.
        run: answers a lookup by name and terms with its first result.
        templar: renders a templated ``DOMAIN_PRIMARY``; ``None`` takes it as
            given.

    Returns:
        The host's merged domain map, its ``DOMAIN_PRIMARY`` and the node onion
        address, empty without Tor.
    """
    primary = variables.get("DOMAIN_PRIMARY") or ""
    if templar is not None and isinstance(primary, str):
        primary = templar.template(primary)
    node = ""
    if tor_serves_host(variables):
        provider = network(TOR).provider
        node = str(run("config", provider, "services.tor.node", "") or "").strip()
    return run("domains"), str(primary), node


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('network_siblings', domain) }}
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1 or not str(terms[0] or "").strip():
            raise AnsibleError("lookup('network_siblings', domain) expects one domain")
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        def _run(name: str, *args: str) -> Any:
            return lookup_loader.get(name, loader=self._loader, templar=templar).run(
                list(args), variables=variables
            )[0]

        return [
            served_siblings(str(terms[0]), *sibling_scope(variables, _run, templar))
        ]
