from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.url.join import url_join

RECEIVER_PATH = "services.sso.oidc.backchannel_logout_path"


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('backchannel_receiver', application_id) }}

    Returns ``services.sso.oidc.backchannel_logout_path`` of ``application_id``
    joined to ``lookup('landing_url', application_id)``.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1 or not str(terms[0] or "").strip():
            raise AnsibleError(
                "lookup('backchannel_receiver', application_id) expects one application id"
            )
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}
        application_id = str(terms[0]).strip()

        def _run(name: str, *args: str) -> Any:
            return lookup_loader.get(name, loader=self._loader, templar=templar).run(
                list(args), variables=variables
            )[0]

        return [
            url_join(
                [
                    _run("landing_url", application_id),
                    _run("config", application_id, RECEIVER_PATH),
                ]
            )
        ]
