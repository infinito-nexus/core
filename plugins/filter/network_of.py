from __future__ import annotations

from utils.networks.instances import (
    labelled,
    labelled_file,
    network_instances,
    vhost_label,
)
from utils.networks.reachability import network, network_of, sibling_domain


def network_sibling(domain: str, name: str, primary: str, node: str) -> str:
    """Return ``domain`` translated into the network ``name``, or ``""`` when
    it has no name there (see ``utils.networks.reachability.sibling_domain``)."""
    return sibling_domain(domain, name, primary, node) or ""


def network_suffix(name: str) -> str:
    """Return the domain suffix of the network ``name``, ``""`` for clearnet."""
    return network(name).suffix or ""


def in_network(domains, name: str) -> list[str]:
    """Return the entries of ``domains`` that belong to the network ``name``."""
    return [domain for domain in domains if network_of(domain) == name]


class FilterModule:
    def filters(self):
        return {
            "network_of": network_of,
            "network_sibling": network_sibling,
            "network_suffix": network_suffix,
            "in_network": in_network,
            "network_instances": network_instances,
            "vhost_label": vhost_label,
            "labelled": labelled,
            "labelled_file": labelled_file,
        }
