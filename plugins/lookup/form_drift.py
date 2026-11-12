from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.merge.with_defaults import merge_with_defaults
from utils.cache import ROLES_DIR
from utils.cache.applications import (  # nocheck: lookup-cache-import  the fail-closed rule needs the unrendered application, which the applications lookup never returns
    get_application_defaults,
)
from utils.cache.base import _resolve_override_mapping
from utils.roles.applications import forms
from utils.roles.applications.converge import values
from utils.roles.applications.drift import drift, secret_values
from utils.roles.mapping import ROLE_FILE_META_FORMS


def raw_application(
    application_id: str, variables: Mapping[str, Any], templar: Any
) -> dict[str, Any]:
    """Return ``applications.<role>`` with the inventory merged over the role defaults, unrendered.

    Args:
        application_id: the role.
        variables: the play variables that carry the inventory's ``applications``.
        templar: the lookup's templar.
    """
    overrides = _resolve_override_mapping(variables, "applications", templar=templar)
    override = overrides.get(application_id)
    return merge_with_defaults(
        {application_id: get_application_defaults().get(application_id, {})},
        {application_id: override if isinstance(override, Mapping) else {}},
    )[application_id]


def _flat(current: Any, managed: Mapping, application_id: str) -> dict[str, Any]:
    if not isinstance(current, Mapping):
        raise AnsibleError(
            "form_drift: current must map each form to its fields and values"
        )
    flat = {}
    for form, fields in current.items():
        if form not in managed or not isinstance(fields, Mapping):
            raise AnsibleError(
                f"form_drift: {application_id} declares no form {form!r} "
                f"in {ROLE_FILE_META_FORMS}"
            )
        flat.update({f"{form}.{field}": value for field, value in fields.items()})
    return flat


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
    ) -> list[list[str]]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "lookup('form_drift', application_id, current) expects two terms."
            )
        application_id, current = str(terms[0]), terms[1]
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}
        applications = self._spot("applications", [], variables, **kwargs)
        application = applications.get(application_id)
        managed = application.get("forms") if isinstance(application, Mapping) else None
        if not isinstance(managed, Mapping):
            raise AnsibleError(
                f"form_drift: {application_id} has no {ROLE_FILE_META_FORMS}"
            )
        read = _flat(current, managed, application_id)
        users = self._spot("users", [], variables, **kwargs)
        try:
            desired = {
                f"{form}.{field}": value
                for form in current
                for field, value in values(
                    form, managed, application, users, "enforced"
                ).items()
            }
        except forms.SourceError as exc:
            raise AnsibleError(f"form_drift: {application_id}: {exc}") from exc
        return [
            drift(
                application_id,
                managed,
                desired,
                read,
                forms.role_credentials(ROLES_DIR / application_id),
                raw_application=raw_application(application_id, variables, templar),
                secrets=secret_values(applications, users),
            )
        ]
