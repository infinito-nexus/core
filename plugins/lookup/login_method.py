from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications import login


class LookupModule(LookupBase):
    """lookup('login_method', application_id, method)

    Args:
        application_id: the application whose sign-in page offers the method.
        method: one of ``utils.roles.applications.login.METHODS``.

    Returns:
        The default of ``services.<entity>.login.method.<method>.enabled``,
        derived from the application's ``sso`` and ``ldap`` service flags.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "lookup('login_method', application_id, method) expects 2 terms."
            )
        application_id, method = (str(term).strip() for term in terms)
        config = lookup_loader.get(
            "config", loader=self._loader, templar=getattr(self, "_templar", None)
        )
        sso = boolean(
            config.run([application_id, "services.sso.enabled"], variables=variables)[0]
        )
        ldap_service = config.run(
            [application_id, "services.ldap", None], variables=variables
        )[0]
        ldap = isinstance(ldap_service, dict) and boolean(
            config.run([application_id, "services.ldap.enabled"], variables=variables)[
                0
            ]
        )
        try:
            return [login.default(method, sso, ldap)]
        except ValueError as error:
            raise AnsibleError(f"login_method: {error}") from error
