from __future__ import annotations

from functools import partial
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.lookup.network_siblings import sibling_scope
from utils.cache.base import _render_with_templar
from utils.domains.served import declares_served, served_domains, served_parent
from utils.tls.common import (
    iter_domains,
    redirect_targets,
    wildcard_certificate_available,
)
from utils.tls.overrides import with_rendered_tls


class LookupModule(LookupBase):
    """
    Usage::

        {{ lookup('served_domains', application_ids=CURRENT_PLAY_DOMAINS.keys() | list) }}

    Returns ``{"entries", "problems", "parents"}`` of
    ``utils.domains.served.served_domains`` for those applications, each
    parent on the network its application is served on (``served_parent``).
    It never fails on a declaration or a member: the constructor keeps
    ``entries``, and the role that declares ``domains.served`` fails on its own
    ``problems``.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, list[Any]]]:
        if terms:
            raise AnsibleError(
                "lookup('served_domains') takes no terms; pass application_ids=[...]"
            )
        application_ids = kwargs.get("application_ids")
        if not isinstance(application_ids, list):
            raise AnsibleError(
                "lookup('served_domains'): application_ids must be a list"
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        def _run(name: str, *args: Any) -> Any:
            return lookup_loader.get(name, loader=self._loader, templar=templar).run(
                list(args), variables=variables
            )[0]

        ids = [str(application_id) for application_id in application_ids]
        applications = _run("applications")
        if not declares_served(applications, ids):
            return [{"entries": [], "problems": [], "parents": []}]
        domain_map, primary, node = sibling_scope(variables, _run, templar)
        domains = [d for value in domain_map.values() for d in iter_domains(value)]
        known = [*domains, *redirect_targets(variables)]
        render = partial(
            _render_with_templar,
            templar=templar,
            variables=variables,
            raw_applications=applications,
        )
        rendered = {
            app_id: with_rendered_tls(
                applications[app_id], render, where=f"served_domains: '{app_id}'"
            )
            for app_id in ids
            if isinstance(applications.get(app_id), dict)
        }
        return [
            served_domains(
                {**applications, **rendered},
                _run("users"),
                ids,
                wildcard_certificate=lambda app: wildcard_certificate_available(
                    app, variables
                ),
                known_domains=[*known, *(f"www.{domain}" for domain in known)],
                parent_of=lambda app_id, parent: served_parent(
                    parent, iter_domains(domain_map.get(app_id)), primary, node
                ),
            )
        ]
