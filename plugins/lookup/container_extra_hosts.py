"""Lookup ``container_extra_hosts``: the single emitter of ``extra_hosts:``.

Compose rejects a mapping that carries the key twice, so nothing else in the
repo may write ``extra_hosts:`` by hand. Everything a service needs pinned goes
through here, from two sources that are both optional:

1. The SSO back-channel pin, added automatically. On an onion deployment the
   OIDC endpoints handed to an application are public ``.onion`` authorities.
   That is right for the browser, which reaches them through Tor, but
   unroutable for the application's own server-side calls (code-to-token
   exchange, JWKS, userinfo): a container resolves ``.onion`` through Tor's
   resolver, not through DNS. Pinning the provider to a reachable address sends
   those calls over the local network to the proxy that already serves the
   vhost. Skipped unless the application has SSO enabled and the provider vhost
   is an ``.onion`` name, so it is a no-op on clearnet.
2. ``host_alias=true``, which pins ``host.docker.internal`` at whatever reaches
   the host in the effective mode. A container that must talk to a service the
   host publishes -- msmtp relaying through the swarm ingress on :587, for
   instance -- needs the alias, and it must not hardcode ``host-gateway``
   because that breaks under swarm for the reason below.
3. ``extra_hosts=``, whatever the call site needs on top: a peer's overlay VIP,
   or a partner service reachable only on the host.

Entries are ``"name:address"`` strings and are deduplicated in first-seen
order. With nothing to emit the lookup returns an empty string.

The automatic pin follows the effective deploy mode, and in swarm it must NOT be
``host-gateway``: that alias resolves per node, while openresty publishes :80
with ``mode: host`` under ``node.role == manager``, so every replica on a worker
dialled its own gateway and the token exchange died with 'Connection refused'
(7b1839681, measured on penpot in run 31340965955). Swarm therefore gets the
stack host's routable address -- the destination svc-net-tor already sends all
hidden-service traffic to. ``ansible_facts`` carries it because the compose file
is rendered once with the manager as inventory host and swarm applies the same
``extra_hosts`` to every task.

The mode is read as ``compose_mode_force or DEPLOYMENT_MODE`` rather than the
bare cluster mode, because ``container_networks`` resolves attachments through
that same effective mode: a role with an override must not lose its pin and its
overlay at once.

Caller-supplied entries are passed through untouched, so a call site that needs
a different address per mode must still decide that itself.

Usage in any service template:

    {{ lookup('container_extra_hosts') | indent(4) }}
    {{ lookup('container_extra_hosts',
              extra_hosts=['host.docker.internal:host-gateway']) | indent(4) }}
    {{ lookup('container_extra_hosts', application_id='web-app-nextcloud') | indent(4) }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import resolve_var

HOST_GATEWAY = "host-gateway"
DOCKER_INTERNAL_HOST = "host.docker.internal"
SSO_PROVIDER = "web-app-keycloak"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
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

        entries = self._sso_pins(application_id)
        if _to_bool(self._render(kwargs.get("host_alias", False)), strict=False):
            entries.append(
                f"{DOCKER_INTERNAL_HOST}:{self._gateway_address(DOCKER_INTERNAL_HOST)}"
            )
        entries += self._caller_entries(kwargs.get("extra_hosts"))
        merged = list(dict.fromkeys(entries))
        if not merged:
            return [""]

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
        if not provider_host.endswith(".onion"):
            return []

        return [
            f"{DOCKER_INTERNAL_HOST}:{HOST_GATEWAY}",
            f"{provider_host}:{self._gateway_address(provider_host)}",
        ]

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
