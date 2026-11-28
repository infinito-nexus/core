"""Project an agent's egress from its compiled firewall role.

The firewall's own egress surface is ``egress_allowlist`` in
:mod:`utils.firewall.compile`. This module builds on it: the allowlisted hosts
outside the platform, the remote hosts an agent's account grants reach, the
vendor hosts a login-mode workspace adds, and the policy of the hypervisor-side
egress proxy in front of an agent VM.
"""

from __future__ import annotations

from urllib.parse import urlsplit

from utils.firewall.compile import Resolved, _matches, egress_allowlist
from utils.firewall.parse import normalise_host

GITHUB_HOSTS = ("github.com", "api.github.com")


def remote_egress(resolved: Resolved) -> list[str]:
    """Return the allowlisted hosts outside the platform: every entry of
    ``egress_allowlist`` that no deploy variable names, since a ``${VAR}``
    host is one the deploy renders for the platform itself."""
    return [host for host in egress_allowlist(resolved) if "${" not in host]


def account_hosts(grants: list[str], remote_bases: dict[str, str]) -> list[str]:
    """Return the exact remote hosts the account grants reach: GitHub's web and
    API host, and the host of the base URL of every provider pointed to a
    remote instance. A provider without a remote base is the platform's own
    app and adds no remote host.

    Args:
        grants: the agent's account grants, ``<provider>/<label>``.
        remote_bases: provider to the base URL of its remote instance.
    """
    hosts: set[str] = set()
    for grant in grants:
        provider = grant.split("/")[0]
        if provider == "github":
            hosts |= set(GITHUB_HOSTS)
        elif provider in remote_bases:
            hosts.add(normalise_host(urlsplit(remote_bases[provider]).netloc))
    return sorted(hosts)


def login_hosts(providers: dict[str, dict], runtime: str) -> list[str]:
    """Return the vendor hosts a login-mode workspace of ``runtime`` adds to
    its egress: the ``login_hosts`` of every declared provider that names the
    runtime, and nothing else.

    Args:
        providers: provider name to its parsed agents/firewall/providers/ file.
        runtime: the agent's runtime.
    """
    return sorted(
        {
            host
            for provider in providers.values()
            if runtime in (provider.get("runtimes") or [])
            for host in provider.get("login_hosts") or []
        }
    )


def _egress_denied(resolved: Resolved, host: str) -> bool:
    return any(
        _matches(rule, "egress", normalise_host(host), None) for rule in resolved.deny
    )


def vm_egress_proxy(
    resolved: Resolved, model_access: str, vendor_hosts: list[str], platform: dict
) -> dict:
    """Return the policy of the hypervisor-side egress proxy in front of an
    agent VM: the hosts the proxy refuses and the hosts it admits by TLS SNI or
    HTTP Host header, refuse before admit, every other destination refused.
    Every VM reaches the MCP adapter and its own forks; gateway mode adds the
    model gateway, login mode the vendor hosts instead. A deny rule still
    removes any of them. DNS goes only to the pinned resolver.

    Args:
        resolved: the agent's resolved firewall role.
        model_access: ``gateway`` or ``login``.
        vendor_hosts: the result of ``login_hosts`` for the agent's runtime.
        platform: ``model_gateway`` and ``mcp_adapter`` host, ``forks`` (the
            hosts of the agent's forks) and ``resolver`` (the hypervisor's
            resolver address).
    """
    candidates = set(egress_allowlist(resolved))
    candidates |= {normalise_host(platform["mcp_adapter"])}
    candidates |= {normalise_host(host) for host in platform["forks"]}
    if model_access == "login":
        candidates |= {normalise_host(host) for host in vendor_hosts}
    else:
        candidates |= {normalise_host(platform["model_gateway"])}
    return {
        "refuse": sorted({r.target for r in resolved.deny if r.kind == "egress"}),
        "admit": sorted(h for h in candidates if not _egress_denied(resolved, h)),
        "match": ["sni", "host"],
        "order": ["refuse", "admit"],
        "unmatched": "deny",
        "outside_proxy": ["dns-to-resolver", "dhcp"],
        "resolver": platform["resolver"],
    }
