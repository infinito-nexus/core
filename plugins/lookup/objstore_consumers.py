"""Enumerate the roles that consume a given object-store engine on this host.

Returns the sorted role ids deployed on the current host whose merged
applications config binds them to ``engine`` as a shared object store. The
provider role is excluded. Selection is by that binding alone -- no naming
convention is assumed of a consumer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.lookup.objstore import OBJSTORE_ENGINES, OBJSTORE_PROVIDER_ROLE

if TYPE_CHECKING:
    from collections.abc import Sequence


def _declares(applications: dict[str, Any], role_id: str, engine: str) -> bool:
    """Whether the merged config carries a ``services.<engine>`` block."""
    config = applications.get(role_id)
    if not isinstance(config, dict):
        return False
    services = config.get("services")
    return isinstance(services, dict) and engine in services


class LookupModule(LookupBase):
    def run(
        self,
        terms: Sequence[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = list(terms or [])
        if len(terms) != 1:
            raise AnsibleError(
                "objstore_consumers: expected exactly one term -- the engine "
                f"name, one of {', '.join(OBJSTORE_ENGINES)}."
            )
        engine = str(terms[0]).strip()
        if engine not in OBJSTORE_ENGINES:
            raise AnsibleError(
                f"objstore_consumers: unknown engine {engine!r}; "
                f"expected one of {', '.join(OBJSTORE_ENGINES)}."
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        group_names = vars_.get("group_names") or []
        provider = OBJSTORE_PROVIDER_ROLE[engine]
        templar = getattr(self, "_templar", None)

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=vars_)[0]
        objstore = lookup_loader.get("objstore", loader=self._loader, templar=templar)

        consumers: list[str] = []
        for group in group_names:
            role_id = str(group)
            if role_id == provider or not _declares(applications, role_id, engine):
                continue
            binding = objstore.run([role_id], variables=vars_)[0]
            if not isinstance(binding, dict):
                continue
            if binding.get("engine") != engine or not binding.get("shared"):
                continue
            consumers.append(role_id)

        return [sorted(set(consumers))]
