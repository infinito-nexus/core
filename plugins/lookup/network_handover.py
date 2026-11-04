"""Whether a vhost is a network sibling its application hands over to clearnet."""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.reachability import network_of


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('network_handover', application_id, domain) }}

    Returns True when ``application_id`` opts into
    ``networks.reachability.handover`` and ``domain`` lies in another network
    than the application's canonical domain, so its vhost only redirects there.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 2 or not all(str(t or "").strip() for t in terms):
            raise AnsibleError(
                "lookup('network_handover', application_id, domain) expects two terms"
            )
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        application_id, domain = (str(term).strip() for term in terms)

        def _run(name: str, *args: Any) -> Any:
            return lookup_loader.get(name, loader=self._loader, templar=templar).run(
                list(args), variables=variables
            )[0]

        handover = _run(
            "config", application_id, "networks.reachability.handover", False
        )
        if not isinstance(handover, bool):
            raise AnsibleError(
                f"network_handover: {application_id}: networks.reachability.handover must be a boolean"
            )
        if not handover:
            return [False]
        return [network_of(domain) != network_of(str(_run("domain", application_id)))]
