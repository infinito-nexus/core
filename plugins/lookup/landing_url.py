"""The URL a browser in the rendered network lands on for an application."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('landing_url', application_id) }}

    Returns the ``url.base`` of ``application_id`` in the network of the vhost
    being rendered, aligned the way ``lookup('tls', application_id, 'url.base')``
    aligns it, unless the application hands that network over: its sibling
    there only redirects, so the canonical ``url.base`` it redirects to is
    returned instead.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1 or not str(terms[0] or "").strip():
            raise AnsibleError(
                "lookup('landing_url', application_id) expects one application id"
            )
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        application_id = str(terms[0]).strip()

        def _run(name: str, *args: str) -> Any:
            return lookup_loader.get(name, loader=self._loader, templar=templar).run(
                list(args), variables=variables
            )[0]

        aligned = str(_run("tls", application_id, "url.base"))
        host = urlsplit(aligned).hostname or ""
        if host and _run("network_handover", application_id, host):
            canonical = str(_run("domain", application_id))
            return [str(_run("tls", canonical, "url.base"))]
        return [aligned]
