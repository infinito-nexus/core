from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.lookup.tor_ports import _as_bool, collect_exposed_ports


def is_reachable(applications: dict[str, Any], application_id: str) -> bool:
    """True when *application_id* is reachable over the node onion, i.e. when
    svc-net-tor is deployed for it (``services.tor.enabled``) AND at least one
    of its services opts in with ``exposed: true``, which is what earns a
    ``HiddenServicePort`` (``collect_exposed_ports``).

    Both halves are required: ``tor.enabled`` is the dependency edge, not the
    port forward, so a client picking the Tor transport from that flag alone
    dials a port with no HiddenServicePort and no host publish.
    """
    config = (applications or {}).get(application_id) or {}
    services = config.get("services") if isinstance(config, dict) else None
    if not isinstance(services, dict):
        return False
    tor = services.get("tor")
    if not (isinstance(tor, dict) and _as_bool(tor.get("enabled"))):
        return False
    return bool(collect_exposed_ports(applications, [application_id]))


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('tor_reachable', application_id) }}

    Returns whether *application_id* is reachable over the node onion in the
    current (variant-merged) applications view -- see ``is_reachable``.

    - parameters:
        1) application_id
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[bool]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('tor_reachable', application_id) expects exactly 1 term."
            )
        application_id = str(terms[0]).strip()
        if not application_id:
            raise AnsibleError(
                "lookup('tor_reachable', application_id): application_id is empty."
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        applications = lookup_loader.get(
            "applications",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([], variables=variables, roles_dir=kwargs.get("roles_dir"))[0]

        return [is_reachable(applications, application_id)]
