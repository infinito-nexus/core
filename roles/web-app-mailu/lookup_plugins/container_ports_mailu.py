"""Lookup ``container_ports_mailu``: the compose ``ports:`` block for Mailu's front.

What gets published follows the TLS flavor, not the port catalogue. The
``email`` lookup turns ``tls`` off for an ``.onion`` host -- Tor already carries
the encryption and no authority issues a certificate for a v3 address -- and
``templates/env.j2`` renders ``TLS_FLAVOR=notls`` from that same value. Mailu's
front then opens no implicit-TLS listener, so publishing 465/993/995 anyway
advertises endpoints nothing serves.

The protocols come from ``MAILU_PORTS`` (``services.mailu.ports.internal``), so
declaring a port in the role meta is enough to publish it. The terms are handed
to the ``container_ports`` SPOT from here rather than from the template: a
lookup call cannot spread a built list into positional terms, and writing the
set out twice for the two TLS flavors duplicates it.

Usage:

    {{ lookup('container_ports_mailu') | indent(4) }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import resolve_var

SERVICE = "mailu"
IMPLICIT_TLS = ("smtps", "pop3s", "imaps")
LOOPBACK = ("http",)


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("container_ports_mailu lookup takes no positional terms")

        self._vars = (
            variables or getattr(self._templar, "available_variables", {}) or {}
        )

        protocols = list(self._protocols())
        if not self._tls():
            protocols = [p for p in protocols if p not in IMPLICIT_TLS]

        bind, public = self._var("DOCKER_BIND_HOST"), self._var("MAILU_IP4_PUBLIC")
        return self._lookup("container_ports").run(
            [
                [SERVICE, protocol, bind if protocol in LOOPBACK else public]
                for protocol in protocols
            ],
            variables=self._vars,
        )

    def _protocols(self) -> dict[str, Any]:
        """The declared internal ports, keyed by protocol.

        Raises:
            AnsibleError: the role meta declares none, which would publish an
                empty block instead of failing where the declaration is missing.
        """
        ports = resolve_var(
            getattr(self, "_templar", None), self._vars.get("MAILU_PORTS", {})
        )
        if not isinstance(ports, dict) or not ports:
            raise AnsibleError(
                "container_ports_mailu: MAILU_PORTS is empty; "
                "services.mailu.ports.internal declares no port"
            )
        return ports

    def _tls(self) -> bool:
        """Whether the deployment speaks implicit TLS, from the email SPOT.

        Raises:
            AnsibleError: the lookup returned no ``tls`` flag; guessing one
                would silently publish or drop three ports.
        """
        email = self._lookup("email").run(
            [self._var("application_id")], variables=self._vars
        )[0]
        if not isinstance(email, dict) or "tls" not in email:
            raise AnsibleError(
                "container_ports_mailu: the email lookup returned no tls flag"
            )
        return boolean(email["tls"], strict=False)

    def _lookup(self, name: str) -> Any:
        return lookup_loader.get(
            name, loader=self._loader, templar=getattr(self, "_templar", None)
        )

    def _var(self, name: str) -> str:
        """Read one play var, rendered, as a stripped string.

        Args:
            name: variable name; role vars reach a lookup as templates.
        """
        return str(
            resolve_var(getattr(self, "_templar", None), self._vars.get(name, "")) or ""
        ).strip()
