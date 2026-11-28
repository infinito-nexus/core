"""Lookup `field_locks`: what the shared lock renderer locks in an application.

    {{ lookup('field_locks', application_id).locks | to_inline_js }}

Returns ``{"locks": [...], "languages": [...] | None, "profile": {...}}`` for
``roles/sys-front-inj-javascript/templates/profile_lock.js.j2``, its catalogue
and the server guards. ``locks`` holds the entry
``utils.roles.applications.forms.locks`` builds for every ``enforced`` field of
the role's ``meta/forms.yml``; an ``sso.<ATTRIBUTE>`` field comes without
``path``, so the renderer shows the profile warning and offers no unlock, and a
role without the file locks nothing. ``languages`` is the role's
``services.sso.profile.languages``, or ``None`` for a role that declares none,
whose page then carries every catalogue language. ``profile`` maps each
``sso.<ATTRIBUTE>`` field to its selector.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR
from utils.roles.applications import forms, sso_fields

PROFILE_PATH = ("services", "sso", "profile")


def _node(tree: Any, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if not isinstance(tree, Mapping) or key not in tree:
            return None
        tree = tree[key]
    return tree


class LookupModule(LookupBase):
    def _spot(
        self, name: str, terms: list[str], variables: dict[str, Any], **kwargs: Any
    ) -> Any:
        return lookup_loader.get(
            name,
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run(terms, variables=variables, **kwargs)[0]

    def run(
        self, terms, variables: dict[str, Any] | None = None, **kwargs: Any
    ) -> list[dict[str, Any]]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('field_locks', application_id) expects one term."
            )
        application_id = str(terms[0])
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}
        application = self._spot("applications", [application_id], variables, **kwargs)
        managed = application.get("forms")
        if not isinstance(managed, Mapping) or not managed:
            managed = {}
        try:
            entries = (
                forms.locks(
                    application_id,
                    managed,
                    application,
                    self._spot("users", [], variables, **kwargs),
                    forms.role_credentials(ROLES_DIR / application_id),
                )
                if managed
                else []
            )
        except forms.SourceError as exc:
            raise AnsibleError(f"field_locks: {application_id}: {exc}") from exc
        return [
            {
                "locks": entries,
                "languages": _node(application, (*PROFILE_PATH, "languages")),
                "profile": sso_fields.selectors(managed),
            }
        ]
