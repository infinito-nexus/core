from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


def merge_excluded(loopback: list[str], objstore_host: str) -> list[str]:
    """Return the hosts a proxied client must reach directly, in order.

    Args:
        loopback: the loopback spellings, from ``NETWORK_LOOPBACK_HOSTS``.
        objstore_host: object store host, empty when the role stores no
            objects or no engine is active.

    Returns:
        Loopback first, then the object store, without duplicates.
    """
    hosts = list(loopback)
    if objstore_host and objstore_host not in hosts:
        hosts.append(objstore_host)
    return hosts


class LookupModule(LookupBase):
    """
    Usage:
        {{ lookup('proxy_excluded_hosts', application_id) }}
        -> ['127.0.0.1', '::1', 'localhost', 'seaweedfs']

    Single spot for the internal hosts a role's HTTP client must reach without
    its proxy. A role that exports an outbound proxy for one purpose applies it
    to every HTTP call the app makes, so an internal dependency reached by name
    is proxied too and fails; enumerating the exemptions per role is what left
    the object store out of them.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('proxy_excluded_hosts') expects exactly one term: "
                "the application_id."
            )
        application_id = str(terms[0]).strip()
        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        loopback = variables.get("NETWORK_LOOPBACK_HOSTS")
        templar = getattr(self, "_templar", None)
        if templar is not None and isinstance(loopback, str):
            with contextlib.suppress(Exception):
                loopback = templar.template(loopback)
        if not isinstance(loopback, list) or not loopback:
            raise AnsibleError(
                "lookup('proxy_excluded_hosts') needs NETWORK_LOOPBACK_HOSTS "
                "from group_vars/all/08_networks.yml; it resolved to "
                f"{loopback!r}."
            )

        objstore = lookup_loader.get(
            "objstore",
            loader=getattr(self, "_loader", None),
            templar=templar,
        )
        enabled = objstore.run(
            [application_id, "enabled"], variables=variables, **kwargs
        )[0]
        host = ""
        if str(enabled).strip().lower() in {"true", "yes", "on", "1"}:
            host = str(
                objstore.run([application_id, "host"], variables=variables, **kwargs)[0]
            ).strip()

        return [merge_excluded([str(entry) for entry in loopback], host)]
