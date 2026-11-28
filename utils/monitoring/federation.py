"""Where the federation of the platform monitoring share lives: the digest
file directory of the nginx lookup and the domain ``/federate`` answers on."""

from __future__ import annotations

import importlib
from pathlib import Path

from utils import PROJECT_ROOT

from .hosts import DOMAIN

PROMETHEUS_APP = "web-app-prometheus"
OPENRESTY_VOLUMES = ("roles", "svc-prx-openresty", "meta", "volumes.yml")


def configuration_base(core):
    """Args:
        core: the core tree.

    Returns:
        ``directories.configuration.base`` of the nginx lookup, derived as it
        derives it from the ``nginx`` volume of ``svc-prx-openresty``.
    """
    from utils.cache.yaml import load_yaml

    nginx = load_yaml(Path(core, *OPENRESTY_VOLUMES))["nginx"]["path"]
    return f"{str(nginx).rstrip('/')}/conf.d/"


def _canonical(domains):
    canonical = domains.get("canonical") if isinstance(domains, dict) else None
    return list(
        (canonical.values() if isinstance(canonical, dict) else canonical) or []
    )


def derived_canonical(primary):
    """Args:
        primary: the host's ``DOMAIN_PRIMARY``, checked as a lowercase domain
            before it is rendered.

    Returns:
        The canonical domains of ``web-app-prometheus`` that core's
        ``utils.domains.list`` derives from the role's ``meta/domains.yml``,
        as the deploy derives them.
    """
    domains = importlib.import_module("utils.domains.list")
    mapping = importlib.import_module("utils.roles.mapping")
    meta = domains.load_yaml_mapping(
        Path(PROJECT_ROOT, "roles", PROMETHEUS_APP, mapping.ROLE_FILE_META_DOMAINS)
    )
    return _canonical(
        domains.render_domain_value(
            meta, {"DOMAIN_PRIMARY": primary}, f"{PROMETHEUS_APP}.domains"
        )
    )


def federation_domain(variables):
    """Args:
        variables: the host variables of ``ansible-inventory --host``.

    Returns:
        The domain of the host's ``web-app-prometheus`` vhost ``/federate``
        answers on, which the ``monitoring`` template scrapes with the
        federation bearer and the release probes: the inventory's first
        canonical domain when it is ``DOMAIN_PRIMARY`` or a subdomain of it,
        else ``derived_canonical`` of ``DOMAIN_PRIMARY``, so the bearer never
        goes to a host outside the instance's own domain.

    Raises:
        ValueError: no lowercase ``DOMAIN_PRIMARY``, or nothing derived.
    """
    primary = variables.get("DOMAIN_PRIMARY")
    if not (isinstance(primary, str) and DOMAIN.fullmatch(primary)):
        raise ValueError(
            f"names no lowercase DOMAIN_PRIMARY for the federation domain of"
            f" {PROMETHEUS_APP}: {primary!r}"
        )
    application = (variables.get("applications") or {}).get(PROMETHEUS_APP) or {}
    pinned = _canonical((application.get("server") or {}).get("domains"))
    first = pinned[0] if pinned else None
    if isinstance(first, str) and DOMAIN.fullmatch(first) and _within(first, primary):
        return first
    derived = derived_canonical(primary)
    if not (derived and isinstance(derived[0], str) and DOMAIN.fullmatch(derived[0])):
        raise ValueError(f"derives no federation domain of {PROMETHEUS_APP}")
    return derived[0]


def _within(domain, primary):
    return domain == primary or domain.endswith(f".{primary}")
