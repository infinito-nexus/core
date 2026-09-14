from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

_HOST_NAME_MAX = 63


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('container_hostname', application_id) }}

    The Docker/OCI hostname for an application's container: ``bounded_name``
    at the 63-byte limit sethostname(2) enforces.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('container_hostname', application_id) expects exactly 1 term"
            )

        return lookup_loader.get(
            "bounded_name",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        ).run([terms[0], _HOST_NAME_MAX], variables=variables, **kwargs)
