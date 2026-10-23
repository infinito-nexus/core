"""Per-network instances of a process that serves one network at a time."""

from __future__ import annotations

from typing import Any

from utils.networks.reachability import network, network_of
from utils.tls_common import iter_domains


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
