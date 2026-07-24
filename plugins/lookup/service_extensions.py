"""Aggregate per-consumer service extensions across all running roles.

Usage:
  {{ lookup('service_extensions', 'postgres') }}

Returns ``{consumer_id: [extension, …]}`` for every role in
``group_names`` whose ``services.<service>`` block is enabled and
declares a non-empty ``extensions`` list.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

if TYPE_CHECKING:
    from collections.abc import Sequence


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _extract_extensions(service_block: dict[str, Any]) -> list[str]:
    raw = service_block.get("extensions")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


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
                "service_extensions: expected exactly one term — the "
                "service name (e.g. 'postgres')."
            )
        service_name = str(terms[0]).strip()
        if not service_name:
            raise AnsibleError("service_extensions: service name must be non-empty")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        group_names = vars_.get("group_names", [])
        if not isinstance(group_names, list):
            raise AnsibleError(
                "service_extensions: required variable 'group_names' must be a list"
            )

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        result: dict[str, list[str]] = {}
        for raw_consumer_id in group_names:
            consumer_id = str(raw_consumer_id)
            services = _as_mapping(
                _as_mapping(applications.get(consumer_id)).get("services")
            )
            block = _as_mapping(services.get(service_name))
            if not bool(block.get("enabled")):
                continue
            extensions = _extract_extensions(block)
            if extensions:
                result[consumer_id] = extensions

        return [result]
