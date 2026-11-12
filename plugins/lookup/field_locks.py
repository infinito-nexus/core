"""Lookup `field_locks`: what the shared lock renderer locks in an application.

    {{ lookup('field_locks', application_id).locks | to_inline_js }}

Returns ``{"locks": [...], "languages": [...] | None}`` for
``roles/sys-front-inj-javascript/templates/profile_lock.js.j2`` and its
catalogue. In ``locks`` the role's ``services.sso.profile.locked`` selectors,
when it declares them, come first as one entry without ``page`` and ``path``:
the SSO login owns those fields, so the renderer shows the profile warning and
offers no unlock. Every ``enforced`` field of the role's ``meta/forms.yml``
follows as the entry ``utils.roles.applications.forms.locks`` builds; a role
with neither locks nothing. ``languages`` is the role's
``services.sso.profile.languages``, or ``None`` for a role that declares none,
whose page then carries every catalogue language.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.cache import ROLES_DIR
from utils.roles.applications import forms

PROFILE_PATH = ("services", "sso", "profile")


def _node(tree: Any, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if not isinstance(tree, Mapping) or key not in tree:
            return None
        tree = tree[key]
    return tree


def profile_entry(application: Mapping) -> list[dict[str, Any]]:
    """Return the entry of the SSO profile lock, if the role declares one.

    Args:
        application: the rendered ``applications.<role>``.
    """
    locked = _node(application, (*PROFILE_PATH, "locked"))
    if not isinstance(locked, Mapping) or not locked:
        return []
    return [
        {
            "page": None,
            "selector": ",".join(locked.values()),
            "label": None,
            "path": None,
            "secret": False,
        }
    ]


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
        entries = profile_entry(application)
        if isinstance(managed, Mapping) and managed:
            entries += forms.locks(
                application_id,
                managed,
                application,
                self._spot("users", [], variables, **kwargs),
                forms.role_credentials(ROLES_DIR / application_id),
            )
        return [
            {
                "locks": entries,
                "languages": _node(application, (*PROFILE_PATH, "languages")),
            }
        ]
