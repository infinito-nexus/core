"""Per-network instances of a process that serves one network at a time."""

from __future__ import annotations

from typing import Any

from utils.networks.reachability import network, network_of
from utils.tls_common import iter_domains, norm_domain, serving_network


def network_instances(app_domains: Any) -> list[dict[str, str]]:
    """One instance per network an application is served on.

    A process that renders network-bound URLs once (one callback, one config)
    serves a single network, so an application served on several networks
    runs one such process per network.

    Args:
        app_domains: the application's domains (str, list or mapping).

    Returns:
        ``{"network": name, "label": label}`` per network in domain order. The
        first network keeps an empty label, so an application served on one
        network keeps its unsuffixed names.
    """
    names: list[str] = []
    for domain in iter_domains(app_domains):
        name = network_of(domain)
        if name not in names:
            names.append(name)
    return [
        {"network": name, "label": network(name).label if index else ""}
        for index, name in enumerate(names)
    ]


def vhost_label(app_domains: Any, domain: Any) -> str:
    """Label of the instance an application renders the vhost ``domain`` for.

    Args:
        app_domains: the application's domains (str, list or mapping).
        domain: the vhost being rendered.

    Returns:
        The ``network_instances`` label of the network the application's own
        lookups resolve for ``domain`` (``utils.tls_common.serving_network``),
        ``""`` for an application without domains.
    """
    served = [norm_domain(item) for item in iter_domains(app_domains)]
    if not served:
        return ""
    name = serving_network(served, norm_domain(domain))
    return next(
        instance["label"]
        for instance in network_instances(app_domains)
        if instance["network"] == name
    )


def labelled(name: str, label: str, separator: str) -> str:
    """Suffix a name with an instance label.

    Args:
        name: the unlabelled name.
        label: the instance label; empty keeps the name.
        separator: joins name and label.

    Returns:
        ``name`` for an empty label, else ``name``, separator and label.
    """
    return f"{name}{separator}{label}" if label else name


def labelled_file(filename: str, label: str) -> str:
    """Suffix a file name's stem with an instance label.

    Args:
        filename: the unlabelled file name, with or without extension.
        label: the instance label; empty keeps the name.

    Returns:
        ``<stem>-<label>.<extension>``, or ``<filename>-<label>`` without an
        extension.
    """
    stem, dot, extension = filename.rpartition(".")
    if not dot:
        return labelled(filename, label, "-")
    return f"{labelled(stem, label, '-')}{dot}{extension}"
