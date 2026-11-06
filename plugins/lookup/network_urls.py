"""A same-node URL in every network the node serves its host on."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit, urlunsplit

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.lookup.network_siblings import network_family, sibling_scope


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('network_urls', url) }}

    Returns ``url`` once per network sibling of its host, canonical network
    first, each with that sibling's scheme, whichever sibling ``url`` names:
    a non-canonical sibling gets the same list as its canonical twin. A URL
    whose host has no sibling comes back alone and unchanged.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1:
            raise AnsibleError("lookup('network_urls', url) expects one url")
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        def _run(name: str, *args: str) -> Any:
            return lookup_loader.get(name, loader=self._loader, templar=templar).run(
                list(args), variables=variables
            )[0]

        url = str(terms[0])
        parts = urlsplit(url)
        host = parts.hostname
        siblings = (
            network_family(host, *sibling_scope(variables, _run, templar))
            if host
            else []
        )
        if len(siblings) < 2:
            return [[url]]
        urls = []
        for sibling in siblings:
            base = urlsplit(_run("tls", sibling, "url.base"))
            urls.append(
                urlunsplit(
                    (base.scheme, base.netloc, parts.path, parts.query, parts.fragment)
                )
            )
        return [urls]
