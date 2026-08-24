"""Lookup ``mailu_extra_hosts``: the host pins Mailu's admin container needs.

Each pin carries its own condition, and the list is handed to the
``container_extra_hosts`` SPOT as its ``extra_hosts=`` argument rather than
written as a second ``extra_hosts:`` key:

* the Keycloak vhost, when Mailu speaks OIDC from inside the containerised rig
  and reaches the provider through the host gateway. Only on clearnet: an
  ``.onion`` provider is pinned by ``container_extra_hosts`` itself, which
  picks the address per deploy mode, and emitting a second line for the same
  name here would leave two addresses in ``/etc/hosts`` under swarm;
* the central database, and
* the central Redis, both only in swarm and only as literal addresses: the
  overlay VIPs are resolved in ``tasks/01_swarm_resolve_peer_vips.yml`` because
  ``extra_hosts`` rejects names. Redis is skipped when the role runs its own.

Returns the entries as separate results, so the call site must use ``query``;
plain ``lookup`` would join them into one comma-separated string.

Usage, through the constant in ``vars/main.yml``:

    MAILU_EXTRA_HOSTS: "{{ query('mailu_extra_hosts') }}"
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import resolve_var

HOST_GATEWAY = "host-gateway"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError("mailu_extra_hosts lookup takes no positional terms")

        self._vars = (
            variables or getattr(self._templar, "available_variables", {}) or {}
        )

        pins: list[str] = []
        oidc_host = self._var("MAILU_OIDC_HOST")
        if (
            self._flag("DOCKER_IN_CONTAINER")
            and self._flag("MAILU_OIDC_ENABLED")
            and not oidc_host.endswith(".onion")
        ):
            pins.append(f"{oidc_host}:{HOST_GATEWAY}")

        if self._var("DEPLOYMENT_MODE") == "swarm":
            pins.append(
                f"{self._var('MAILU_SWARM_DB_HOST')}:{self._var('MAILU_SWARM_DB_ADDR')}"
            )
            if not self._redis_is_local():
                pins.append(
                    f"{self._var('MAILU_SWARM_REDIS_HOST')}:"
                    f"{self._var('MAILU_SWARM_REDIS_ADDR')}"
                )

        return pins

    def _redis_is_local(self) -> bool:
        application_id = self._var("application_id")
        return bool(
            lookup_loader.get(
                "engine", loader=self._loader, templar=getattr(self, "_templar", None)
            ).run(["redis", application_id, "local"], variables=self._vars)[0]
        )

    def _var(self, name: str) -> str:
        """Read one play var, rendered, as a stripped string.

        Args:
            name: variable name; role vars reach a lookup as templates.
        """
        templar = getattr(self, "_templar", None)
        return str(resolve_var(templar, self._vars.get(name, "")) or "").strip()

    def _flag(self, name: str) -> bool:
        """Read one play var as a boolean the way Jinja's ``| bool`` would.

        Args:
            name: variable name; an unrecognised value counts as false.
        """
        templar = getattr(self, "_templar", None)
        return boolean(resolve_var(templar, self._vars.get(name, False)), strict=False)
