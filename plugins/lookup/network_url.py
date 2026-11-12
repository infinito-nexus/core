"""A same-node URL moved into the network of the vhost being rendered."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.network_of import in_network
from utils.networks.reachability import network_of


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('network_url', url) }}

    Returns ``url`` with its host swapped for the sibling the node serves in the
    network of ``domain``, the vhost being rendered, and with that sibling's
    scheme. A URL whose host the node does not serve in that network comes back
    unchanged.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1:
            raise AnsibleError("lookup('network_url', url) expects one url")
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        if "domain" not in variables:
            raise AnsibleError(
                "lookup('network_url', url) needs the vhost being rendered in 'domain'"
            )
        templar = getattr(self, "_templar", None)

        def _run(name: str, *args: str) -> Any:
            return lookup_loader.get(name, loader=self._loader, templar=templar).run(
                list(args), variables=variables
            )[0]

        vhost = variables["domain"]
        if templar is not None and isinstance(vhost, str):
            vhost = templar.template(vhost)
        url = str(terms[0])
        parts = urlsplit(url)
        if not parts.hostname:
            return [url]
        siblings = in_network(
            _run("network_siblings", parts.hostname), network_of(str(vhost))
        )
        if not siblings or siblings[0] == parts.hostname:
            return [url]
        base = urlsplit(_run("tls", siblings[0], "url.base"))
        return [
            urlunsplit(
                (base.scheme, base.netloc, parts.path, parts.query, parts.fragment)
            )
        ]
