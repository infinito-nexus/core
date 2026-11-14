from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import resolve_var
from utils.networks.reachability import TOR, is_network

HOST_GATEWAY = "host-gateway"
DOCKER_INTERNAL_HOST = "host.docker.internal"
SSO_PROVIDER = "web-app-keycloak"


def one_per_name(entries: list[str]) -> list[str]:
    """
    Args:
        entries: ``name:address`` mappings in the order they were collected.

    Returns:
        One mapping per name in first-seen order, holding the first address
        seen for it, except that ``host-gateway`` takes ``host.docker.internal``
        whichever address came first.
    """
    chosen: dict[str, str] = {}
    for entry in entries:
        name, _, address = entry.partition(":")
        if name not in chosen or (
            name == DOCKER_INTERNAL_HOST and address == HOST_GATEWAY
        ):
            chosen[name] = address
    return [f"{name}:{address}" for name, address in chosen.items()]


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        """Render the pins this application needs to reach onion-hosted services.

        Keyword Args:
          application_id: role whose pins to resolve; defaults to the play var.
          extra_hosts:    additional `name:address` entries from the caller.
          onion_peers:    URLs or hosts the container calls; each onion one is
                          pinned to the proxy like the SSO provider.
          host_alias:     also pin `host.docker.internal` to the gateway.
          docker_flags:   emit `--add-host=` flags for a `docker run` command
                          line instead of a compose `extra_hosts:` block.

        Returns a single-element list holding the rendered block, or [""].
        """
        if terms:
            raise AnsibleError(
                "container_extra_hosts lookup takes no positional terms; pass "
                "extra_hosts=[...] and application_id= as keyword arguments"
            )

        self._vars = (
            variables or getattr(self._templar, "available_variables", {}) or {}
        )
        application_id = self._render(
            kwargs.get("application_id") or self._vars.get("application_id")
        )
        if not application_id:
            raise AnsibleError(
                "container_extra_hosts lookup: no application_id in the play vars; "
                "pass application_id= explicitly"
            )

        entries = (
            self._sso_pins(application_id)
            + self._mail_pins(application_id)
            + self._onion_peer_pins(kwargs.get("onion_peers"))
        )
        if _to_bool(self._render(kwargs.get("host_alias", False)), strict=False):
            entries.append(
                f"{DOCKER_INTERNAL_HOST}:{self._gateway_address(DOCKER_INTERNAL_HOST)}"
            )
        entries += self._caller_entries(kwargs.get("extra_hosts"))
        merged = one_per_name(entries)
        if _to_bool(self._render(kwargs.get("entries_only", False)), strict=False):
            return merged
        if not merged:
            return [""]

        if _to_bool(self._render(kwargs.get("docker_flags", False)), strict=False):
            return ["\n".join(f"  - --add-host={entry}" for entry in merged)]

        lines = ["extra_hosts:"] + [f'  - "{entry}"' for entry in merged]
        return ["\n".join(lines)]

    def _sso_pins(self, application_id: str) -> list[str]:
        """The provider pin, empty unless this is an onion node running SSO.

        Args:
            application_id: the role whose ``services.sso`` gate decides.

        The gate is read with a default rather than strictly, because roles that
        declare no ``sso`` entry at all are legitimate call sites here -- they
        just have nothing to pin.
        """
        if not bool(
            self._lookup("config", application_id, "services.sso.enabled", False)
        ):
            return []

        provider_host = str(self._lookup("tls", SSO_PROVIDER, "domain") or "").strip()
        if not is_network(provider_host, TOR):
            return []

        return [
            f"{DOCKER_INTERNAL_HOST}:{HOST_GATEWAY}",
            f"{provider_host}:{self._gateway_address(provider_host)}",
        ]

    def _mail_pins(self, application_id: str) -> list[str]:
        """The mail-provider pin, empty unless this is an onion node sending mail.

        Args:
            application_id: the role whose ``services.email`` gate decides.

        The same unroutability as the SSO pin, one service down: an application
        dials the relay by the provider's public name, which on an onion
        deployment resolves only through Tor. ``sys-svc-mail-msmtp`` answers
        that with a SOCKS proxy, but a client with no proxy setting at all --
        Ruby's ``Net::SMTP``, so GitLab queues the mail and reports success
        while nothing leaves -- has no other route to the relay.
        """
        if not bool(
            self._lookup("config", application_id, "services.email.enabled", False)
        ):
            return []

        mail_host = str(
            (self._lookup("email", application_id) or {}).get("host") or ""
        ).strip()
        if not is_network(mail_host, TOR):
            return []

        return [
            f"{DOCKER_INTERNAL_HOST}:{HOST_GATEWAY}",
            f"{mail_host}:{self._gateway_address(mail_host)}",
        ]

    def _onion_peer_pins(self, onion_peers: Any) -> list[str]:
        """The pins of the onion peers the container calls itself.

        Args:
            onion_peers: one URL or host, a list of them, or None. A clearnet
                peer is left to DNS, so the result is empty off onion.
        """
        if not onion_peers:
            return []
        if isinstance(onion_peers, str):
            onion_peers = [onion_peers]

        pins: list[str] = []
        for peer in onion_peers:
            text = str(self._render(peer) or "").strip()
            host = urlsplit(text).hostname if "://" in text else text
            if host and is_network(host, TOR):
                pins.append(f"{host}:{self._gateway_address(host)}")
        return pins

    def _caller_entries(self, extra_hosts: Any) -> list[str]:
        """Normalise the ``extra_hosts=`` argument to a list of mappings.

        Args:
            extra_hosts: one ``"name:address"``, a list of them, or None.
                Entries that render empty are dropped, so a call site can build
                its list with inline conditionals.

        Raises:
            AnsibleError: an entry carries no ``:`` separator, which Docker
                would reject only at deploy time.
        """
        if not extra_hosts:
            return []
        if isinstance(extra_hosts, str):
            extra_hosts = [extra_hosts]

        entries: list[str] = []
        for entry in extra_hosts:
            text = str(self._render(entry) or "").strip()
            if not text:
                continue
            if ":" not in text:
                raise AnsibleError(
                    f"container_extra_hosts: extra_hosts entry '{text}' is not a "
                    "'name:address' mapping"
                )
            entries.append(text)
        return entries

    def _gateway_address(self, provider_host: str) -> str:
        """Resolve what the provider host must point at in the effective mode.

        Args:
            provider_host: only used to name the host in errors.

        Under swarm this is the stack host's address, not the local node's:
        the template renders once on the manager and swarm copies the same
        ``extra_hosts`` to every task, which is what makes the pin reach the
        one node where openresty publishes.
        """
        if self._compose_mode() == "compose":
            return HOST_GATEWAY

        facts = self._vars.get("ansible_facts") or {}
        address = str((facts.get("default_ipv4") or {}).get("address") or "").strip()
        if not address:
            raise AnsibleError(
                f"container_extra_hosts: cannot pin '{provider_host}' outside compose "
                "mode because ansible_facts.default_ipv4.address is unset; the swarm "
                f"pin must carry the stack host's address, not the '{HOST_GATEWAY}' "
                "alias, which resolves per node and misses the manager that publishes "
                "the vhost. Gather facts before rendering the service template."
            )
        return address

    def _compose_mode(self) -> str:
        """Resolve the effective deploy mode the way the network lookups do.

        ``compose_mode_force`` is a per-role override of the cluster
        ``DEPLOYMENT_MODE``. Both can still be templates when they reach a
        lookup, so both go through ``resolve_var``, which passes a value
        through unchanged rather than raising when it cannot render.
        """
        templar = getattr(self, "_templar", None)
        mode = str(resolve_var(templar, self._vars.get("DEPLOYMENT_MODE", "compose")))
        forced = resolve_var(templar, self._vars.get("compose_mode_force", ""))
        return str(forced or mode).strip()

    def _render(self, value: Any) -> Any:
        """Template a value read straight out of the play vars.

        Args:
            value: raw var value; ``include_role: vars:`` hands these over
                unrendered, e.g. ``application_id: "{{ some_other_var }}"``.

        Raises:
            AnsibleError: the value stayed a template, which would bake
                ``{{ ... }}`` into the compose file.
        """
        templar = getattr(self, "_templar", None)
        if templar is None or not isinstance(value, str) or "{{" not in value:
            return value
        rendered = templar.template(value)
        if isinstance(rendered, str) and "{{" in rendered:
            raise AnsibleError(
                f"container_extra_hosts: '{value}' did not render; it reached the "
                "lookup untrusted as a template."
            )
        return rendered

    def _lookup(self, name: str, *terms: Any) -> Any:
        return lookup_loader.get(
            name, loader=self._loader, templar=getattr(self, "_templar", None)
        ).run(list(terms), variables=self._vars)[0]
