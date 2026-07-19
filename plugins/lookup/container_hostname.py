from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.domains.primary_domain import get_domain
from utils.roles.entity.name import get_entity_name

# sethostname(2) caps a hostname at 64 bytes; onion subdomains
# (sub.<56-char-onion>.onion) regularly exceed that and make the container
# fail to start with "sethostname: invalid argument".
_HOST_NAME_MAX = 63


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('container_hostname', application_id) }}

    The Docker/OCI hostname for an application's container: its canonical
    primary domain when that fits the kernel's 63-byte limit, otherwise the
    short entity name (e.g. ``xwiki``). Centralises the domain-or-entity
    choice so onion deployments (long ``.onion`` subdomains that overflow
    sethostname(2)) never break container init.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('container_hostname', application_id) expects exactly 1 term"
            )

        application_id = terms[0]
        if not isinstance(application_id, str) or not application_id.strip():
            raise AnsibleError(
                "lookup('container_hostname'): application_id must be a "
                f"non-empty string, got {application_id!r}"
            )
        application_id = application_id.strip()

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
                f"lookup('container_hostname'): failed to resolve domain for "
                f"'{application_id}': {e}"
            ) from e

        name = str(domain or "")
        if 0 < len(name) <= _HOST_NAME_MAX:
            return [name]
        return [get_entity_name(application_id)]
