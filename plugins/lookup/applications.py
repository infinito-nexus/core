from __future__ import annotations

from typing import Any, Dict, Optional

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache import _reset_cache_for_tests as _reset_runtime_lookup_cache
from utils.cache.applications import get_merged_applications


def _reset_cache_for_tests() -> None:
    _reset_runtime_lookup_cache()


class LookupModule(LookupBase):
    def run(
        self,
        terms: Optional[list[Any]],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) > 2:
            raise AnsibleError(
                "applications: expected 0, 1, or 2 terms: "
                "lookup('applications'[, application_id[, default]])"
            )

        applications = get_merged_applications(
            variables=variables
            or getattr(self._templar, "available_variables", {})
            or {},
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        if len(terms) == 0:
            return [applications]

        application_id = str(terms[0]).strip()
        default_provided = len(terms) == 2
        default_value = terms[1] if default_provided else None

        if application_id in applications:
            return [applications[application_id]]

        if default_provided:
            return [default_value]

        raise AnsibleError(
            f"applications: application '{application_id}' not found. "
            f"Known application ids: {sorted(applications)}"
        )
