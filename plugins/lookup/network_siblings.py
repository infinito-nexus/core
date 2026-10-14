"""The vhost domains one logical domain is served under on this host."""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.reachability import NETWORKS, TOR, network, sibling_domain
from utils.tls_common import iter_domains, norm_domain


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
    host = norm_domain(domain)
    variants = [
        variant
        for name in NETWORKS
        if (variant := sibling_domain(host, name, primary, node))
    ]
    for value in domains.values():
        served = [norm_domain(d) for d in iter_domains(value)]
        found = [variant for variant in variants if variant in served]
        if not found:
            continue
        if host in served and host != found[0]:
            return []
        return found
    return [host]


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

        primary = variables.get("DOMAIN_PRIMARY") or ""
        if templar is not None and isinstance(primary, str):
            primary = templar.template(primary)
        provider = network(TOR).provider
        node = ""
        if provider in (variables.get("group_names") or []):
            node = str(_run("config", provider, "services.tor.node", "") or "").strip()
        return [served_siblings(str(terms[0]), _run("domains"), str(primary), node)]
