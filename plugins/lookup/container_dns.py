from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

_TOR_ROLE = "svc-net-tor"


def _serves_only_on_loopback(facts: dict[str, Any]) -> bool:
    """Return whether every resolver the host itself uses is a loopback address.

    Docker drops loopback entries from a container's ``resolv.conf``, so such a
    host leaves its containers with no resolver at all unless they are pointed
    at the bridge the same daemon listens on. A host that also lists a routable
    resolver is fine as it is, hence ``all`` rather than ``any``.
    """
    nameservers = (facts.get("dns") or {}).get("nameservers")
    if not isinstance(nameservers, list) or not nameservers:
        return False
    return all(
        str(server).startswith("127.") or str(server) == "::1" for server in nameservers
    )


def render(value: Any, templar: Any) -> str:
    """Return an inventory value with its Jinja resolved.

    Args:
        value: whatever the inventory holds for the field.
        templar: the lookup's templar, or None outside a play.

    ``networks.internet.dns`` arrives through ``-e @inventories/...`` and is
    read straight out of ``variables``, which hands back whatever the file
    contains. While that was a literal address nobody noticed; an expression
    there reached the daemon as its own source text and docker refused the
    config with ``ParseAddr("{{ ... }}")``.
    """
    text = str(value or "")
    if "{{" not in text:
        return text
    rendered = str(templar.template(text)) if templar is not None else text
    if "{{" in rendered:
        raise AnsibleError(
            f"networks.internet.dns is {text!r} and did not resolve to an "
            f"address. Emitting it would put that source text in daemon.json, "
            f"where docker refuses the whole config."
        )
    return rendered


def resolve_container_dns(
    variables: dict[str, Any], templar: Any = None
) -> list[str]:
    """Return the resolver list for the container runtime, most specific first.

    On a Tor node the node dnsmasq resolves ``.onion`` through Tor's DNSPort
    and everything else through the clearnet upstream, which is what makes
    per-app proxy settings unnecessary. It is only reachable on the docker
    bridge address because docker discards loopback resolvers, and it is
    absent before docker itself is installed, hence the guard.

    The same reachability problem exists without Tor wherever the host resolves
    through a listener of its own on loopback, which is how the simulated
    cluster nodes are wired. Handing containers the declared clearnet address
    there was what a literal bridge address in the inventory used to paper
    over, and that literal went stale the moment the daemon's address pool
    moved the bridge off Docker's default.

    Both deploy modes get the bridge: a Tor node runs the same dnsmasq
    listener in compose and in swarm, so both resolve onions alike.

    The clearnet resolver stays as a second entry so that losing dnsmasq costs
    onion names rather than all name resolution. Duplicates are dropped: where
    the bridge *is* the clearnet resolver, emitting it twice makes daemon.json
    differ between a run before and a run after ``docker0`` exists, and that
    difference restarts the container runtime underneath a live stack.
    """
    facts = variables.get("ansible_facts") or {}
    bridge = ((facts.get("docker0") or {}).get("ipv4") or {}).get("address") or ""
    on_tor_node = _TOR_ROLE in (variables.get("group_names") or [])

    clearnet = render(
        ((variables.get("networks") or {}).get("internet") or {}).get("dns"), templar
    )

    needs_bridge = on_tor_node or _serves_only_on_loopback(facts)
    resolvers = (bridge if needs_bridge else "", clearnet)
    return list(dict.fromkeys(str(r) for r in resolvers if r))


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('container_dns') }}

    Resolver list for the docker daemon's ``dns`` key. Takes no terms.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if terms:
            raise ValueError("lookup('container_dns') takes no positional terms.")
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        return [resolve_container_dns(variables, self._templar)]
