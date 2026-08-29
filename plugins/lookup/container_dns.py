from __future__ import annotations

from ipaddress import ip_network
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.address import subnet_gateway
from utils.templating.ansible import _trust_as_template

_TOR_ROLE = "svc-net-tor"


def _serves_on_the_bridge(variables: dict[str, Any]) -> bool:
    """Return whether a resolver on the docker bridge is there to be used.

    Args:
        variables: the variables in scope for the lookup.

    This used to be inferred from the host's own ``resolv.conf``: every entry a
    loopback address was read as "a listener of ours answers, and containers
    must reach it on the bridge instead". The inference is wrong on any host
    running systemd-resolved or NetworkManager's dnsmasq, whose stubs bind
    ``127.0.0.53`` and ``127.0.0.1`` and nothing else. Those hosts were handed a
    bridge address with no server behind it, which cost them all container DNS -
    an image build failed on ``apk`` resolving nothing while the daemon itself,
    resolving through the host, pulled the same image fine.

    Two things do bind the bridge and both say so: ``svc-net-tor``, whose
    dnsmasq listens there so ``.onion`` resolves, and any deployment that sets
    ``NETWORK_CONTAINER_BRIDGE_RESOLVER``.
    """
    if _TOR_ROLE in (variables.get("group_names") or []):
        return True
    return bool(variables.get("NETWORK_CONTAINER_BRIDGE_RESOLVER"))


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

    ``str()`` drops the ``TrustedAsTemplate`` tag the loader attached, and the
    templar returns an untagged string unrendered. Re-tagging before templating
    is what every sibling lookup does; without it this function would trade the
    daemon's parse error for its own.
    """
    text = str(value or "")
    if "{{" not in text:
        return text
    rendered = (
        str(templar.template(_trust_as_template(text))) if templar is not None else text
    )
    if "{{" in rendered:
        raise AnsibleError(
            f"networks.internet.dns is {text!r} and did not resolve to an "
            f"address. Emitting it would put that source text in daemon.json, "
            f"where docker refuses the whole config."
        )
    return rendered


def bridge_address(variables: dict[str, Any]) -> str:
    """Return the docker bridge gateway containers can reach the host on.

    Args:
        variables: the variables in scope for the lookup.

    ``ansible_facts`` only carries ``docker0`` once the daemon has run, and the
    daemon config is written before that on a fresh node - facts are gathered at
    play start, and nothing re-gathers them after the install. Reading the fact
    alone therefore yields nothing on the very run that has to emit the address,
    which leaves the inner containers pointed at the clearnet resolver and the
    DinD DNS check failing on a domain only the node dnsmasq knows.

    ``default-address-pools`` is where docker takes that address from, so the
    declaration answers before the daemon exists and answers identically
    afterwards. That also keeps daemon.json byte-identical across passes, which
    the fact-derived value could not: it appeared only from the second run on
    and restarted the container runtime under a live stack.

    The fact is not merely late, it is wrong while it is late. Facts are read
    before the daemon config is applied, so ``docker0`` still carries docker's
    own default; writing the pools then moves the bridge underneath it. A swarm
    node measured ``172.17.0.1`` in daemon.json against a live ``10.208.0.1``,
    which is why the declaration answers here and the fact never does.

    The pool's ``size`` bounds the slice docker hands the bridge, so the gateway
    is derived from that slice rather than from the enclosing supernet - they
    agree only while the pool starts on a slice boundary.
    """
    pools = variables.get("NETWORK_DOCKER_ADDRESS_POOLS") or []
    first = (pools[0] or {}) if pools else {}
    base = str(first.get("base") or "")
    if not base:
        return ""
    size = first.get("size")
    try:
        network = ip_network(base, strict=True)
        slice_ = (
            network if size is None else next(network.subnets(new_prefix=int(size)))
        )
        return subnet_gateway(str(slice_))
    except ValueError as exc:
        raise AnsibleError(
            f"networks: the first docker address pool {base!r} holds no gateway "
            f"address, so containers have no way back to the host resolver."
        ) from exc


def public_resolver(variables: dict[str, Any]) -> str:
    """Return the resolver to fall back on when the bridge may serve nothing.

    Args:
        variables: the variables in scope for the lookup.

    Read strictly: a missing declaration must fail the render rather than emit
    a hardcoded address, which the repository forbids and lints for. Only the
    first entry is taken because a resolver list is capped at three and the
    bridge already holds one of those slots.
    """
    resolvers = variables.get("NETWORK_PUBLIC_DNS_RESOLVERS")
    if not resolvers:
        raise AnsibleError(
            "networks: NETWORK_PUBLIC_DNS_RESOLVERS is empty, so a host whose "
            "docker bridge serves no DNS would be left without any resolver."
        )
    return str(resolvers[0])


def resolve_container_dns(variables: dict[str, Any], templar: Any = None) -> list[str]:
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

    Whether a resolver answers on the bridge is not something the host's own
    ``resolv.conf`` can say - a systemd-resolved stub and a node dnsmasq both
    read as loopback-only, and only the second one also binds the bridge. Until
    that is declared rather than inferred, the bridge may be an address nothing
    serves, so it never goes out alone: a list that would carry it by itself
    gets the project's public resolver behind it. Without that the daemon has a
    single dead nameserver and every container and image build loses DNS.
    """
    bridge = bridge_address(variables)

    clearnet = render(
        ((variables.get("networks") or {}).get("internet") or {}).get("dns"), templar
    )

    resolvers = (bridge if _serves_on_the_bridge(variables) else "", clearnet)
    emitted = list(dict.fromkeys(str(r) for r in resolvers if r))
    if emitted == [bridge]:
        emitted.append(public_resolver(variables))
    return emitted


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
