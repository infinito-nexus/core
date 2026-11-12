"""Lookup `form_values`: what a role converges into one form of its ``meta/forms.yml``.

    {{ lookup('form_values', application_id, 'general') }}
    {{ lookup('form_values', application_id, 'general', mode='seeded') }}

Returns each field of the form whose ``when`` holds mapped to the value its
``source`` resolves to in the rendered ``applications.<role>`` and the global
users; ``mode`` keeps only the fields of that mode. A role reads every value
it converges into the form through this lookup, so the lint of
``tests/lint/ansible/roles/meta/test_forms.py`` can match the forms a role
converges against the forms it declares.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.converge import values
from utils.roles.applications.forms import MODES, SourceError
from utils.roles.mapping import ROLE_FILE_META_FORMS


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
        self,
        terms,
        variables: dict[str, Any] | None = None,
        mode: str | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "lookup('form_values', application_id, form) expects two terms."
            )
        if mode is not None and mode not in MODES:
            raise AnsibleError(f"form_values: mode must be one of {list(MODES)}")
        application_id, form = (str(term) for term in terms)
        templar = getattr(self, "_templar", None)
        variables = variables or getattr(templar, "available_variables", {}) or {}
        application = self._spot("applications", [application_id], variables, **kwargs)
        managed = application.get("forms")
        if not isinstance(managed, Mapping) or form not in managed:
            raise AnsibleError(
                f"form_values: {application_id} declares no form {form!r} "
                f"in {ROLE_FILE_META_FORMS}"
            )
        users = self._spot("users", [], variables, **kwargs)
        try:
            return [values(form, managed, application, users, mode)]
        except SourceError as exc:
            raise AnsibleError(f"form_values: {application_id} {form}: {exc}") from exc
