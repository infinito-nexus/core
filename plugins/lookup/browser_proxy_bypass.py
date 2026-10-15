"""Hosts a browser probe reaches without the proxy of the network it probes."""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.reachability import (
    browser_proxy_bypass,
    resolve_node_mode,
    tor_serves_host,
)
from utils.tls_common import iter_domains


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('browser_proxy_bypass', network_name, *extra_hosts) }}

    Returns the hosts a browser probing a page of ``network_name`` on this node
    reaches directly instead of through that network's proxy: the domains of
    the applications deployed here plus ``extra_hosts`` (e.g. the SSO issuer),
    each kept only when its network needs no browser proxy and the node serves
    that network.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or not str(terms[0] or "").strip():
            raise AnsibleError(
                "lookup('browser_proxy_bypass', network, *hosts) expects a network"
            )
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        raw_mode = variables.get("NETWORK_MODE") or ""
        if templar is not None and isinstance(raw_mode, str):
            raw_mode = templar.template(raw_mode)
        try:
            mode = resolve_node_mode(raw_mode, tor_provided=tor_serves_host(variables))
        except ValueError as exc:
            raise AnsibleError(f"browser_proxy_bypass: {exc}") from exc
        domains = lookup_loader.get(
            "domains", loader=self._loader, templar=templar
        ).run([], variables=variables)[0]
        deployed = set(variables.get("group_names") or [])
        hosts = [
            domain
            for app, value in domains.items()
            if app in deployed
            for domain in iter_domains(value)
        ]
        return [browser_proxy_bypass(str(terms[0]), mode, [*hosts, *terms[1:]])]
