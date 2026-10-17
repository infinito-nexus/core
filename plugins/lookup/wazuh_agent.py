from __future__ import annotations

from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.services.wazuh import (
    AGENT_ID,
    AGENT_TIME_RECONNECT,
    MANAGER_ROLE,
)

LOCAL_INVENTORY_HOSTS = ("localhost", "127.0.0.1")


class LookupModule(LookupBase):
    """Return the Wazuh agent entry of the current inventory host.

    The manager pre-registers this entry and the host's agent writes it to its
    ``client.keys``, so both sides read it from here.

    Returns:
        ``{id, name, key, time_reconnect}``. ``name`` is ``DOMAIN_PRIMARY``
        when the inventory host is local (dev and CI name their only host
        ``localhost``, which says nothing in the dashboard), otherwise
        ``inventory_hostname``. ``key`` is the vault-generated agent key.
        ``time_reconnect`` is the agent's reconnect interval in seconds, which
        the manager's wait for the agent has to cover.
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        hostname = str(vars_["inventory_hostname"])
        name = (
            str(self._templar.template(vars_["DOMAIN_PRIMARY"]))
            if hostname in LOCAL_INVENTORY_HOSTS
            else hostname
        )
        key = lookup_loader.get("config", loader=self._loader, templar=templar).run(
            [MANAGER_ROLE, "secrets.credentials.agent_key"], variables=vars_
        )[0]
        return [
            {
                "id": AGENT_ID,
                "name": name,
                "key": key,
                "time_reconnect": AGENT_TIME_RECONNECT,
            }
        ]
