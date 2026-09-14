from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.domains.primary_domain import get_domain
from utils.roles.entity.name import get_entity_name


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('bounded_name', application_id, max_length) }}

    An application's canonical primary domain when it has at most max_length
    characters, otherwise its short entity name (e.g. ``keycloak``).

    Args:
      application_id: the application whose domain names the value.
      max_length: the longest value the consumer accepts; a positive integer.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "lookup('bounded_name', application_id, max_length) expects exactly 2 terms"
            )

        application_id, max_length = terms
        if not isinstance(application_id, str) or not application_id.strip():
            raise AnsibleError(
                "lookup('bounded_name'): application_id must be a "
                f"non-empty string, got {application_id!r}"
            )
        application_id = application_id.strip()

        try:
            limit = int(max_length)
        except (TypeError, ValueError) as e:
            raise AnsibleError(
                f"lookup('bounded_name'): max_length must be an integer, got {max_length!r}"
            ) from e
        if limit < 1:
            raise AnsibleError(
                f"lookup('bounded_name'): max_length must be positive, got {limit}"
            )

        variables = variables or getattr(self._templar, "available_variables", {}) or {}

        domains = lookup_loader.get(
            "domains",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([], variables=variables, roles_dir=kwargs.get("roles_dir"))[0]

        try:
            domain = get_domain(domains, application_id)
        except Exception as e:
            raise AnsibleError(
                f"lookup('bounded_name'): failed to resolve domain for "
                f"'{application_id}': {e}"
            ) from e

        name = str(domain or "")
        if 0 < len(name) <= limit:
            return [name]
        return [get_entity_name(application_id)]
