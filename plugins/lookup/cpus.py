"""The CPU cap of one service, with a percentage resolved against the host.

``lookup('cpus', application_id[, service_name])`` reads
``services.<service_name>.cpus`` and resolves it through
:func:`plugins.filter.resource_filter.resolve_cpus`. A caller neither repeats
the resolution nor has to know that a percentage is read against the host's
raw core count rather than against the fair share, which is what every
consumer of a ``cpus`` value got wrong before this existed.

``service_name`` defaults to the role's entity name.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.filter.resource_filter import resolve_cpus
from plugins.lookup.config import LookupModule as ConfigLookup
from plugins.lookup.resource import LookupModule as ResourceLookup
from utils.roles.entity.name import entity_name


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if not terms or len(terms) > 2:
            raise AnsibleError(
                "lookup('cpus', application_id[, service_name]) expects 1 or 2 terms."
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        application_id = str(terms[0])
        service_name = (
            str(terms[1]) if len(terms) == 2 else entity_name(application_id)
        )

        configured = ConfigLookup().run(
            [application_id, f"services.{service_name}.cpus"],
            variables=vars_,
            **kwargs,
        )[0]
        host_cpus = ResourceLookup().run(["host_cpus"], variables=vars_, **kwargs)[0]
        return [resolve_cpus(configured, host_cpus)]
