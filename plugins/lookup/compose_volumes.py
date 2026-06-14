"""Lookup `compose_volumes`: render the top-level `volumes:` block for
a given application_id. Auto-wires the `applications` registry,
DEPLOYMENT_MODE, and `storage` mapping from the templating context.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.filter.compose_volumes import compose_volumes as _render_compose_volumes
from utils.cache.applications import get_merged_applications


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "compose_volumes lookup requires exactly one term: the application_id"
            )
        application_id = str(terms[0]).strip()
        if not application_id:
            raise AnsibleError(
                "compose_volumes lookup: application_id must be non-empty"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=templar,
        )

        deployment_mode = kwargs.get("deployment_mode")
        if deployment_mode is None:
            deployment_mode = vars_.get("DEPLOYMENT_MODE", "compose")

        storage = kwargs.get("storage")
        if storage is None:
            storage = vars_.get("storage")

        dir_var_lib = kwargs.get("dir_var_lib")
        if dir_var_lib is None:
            dir_var_lib = vars_["DIR_VAR_LIB"]

        if templar is not None:
            with contextlib.suppress(Exception):
                deployment_mode = templar.template(deployment_mode)
            with contextlib.suppress(Exception):
                storage = templar.template(storage)
            with contextlib.suppress(Exception):
                dir_var_lib = templar.template(dir_var_lib)

        rendered = _render_compose_volumes(
            applications,
            application_id,
            extra_volumes=kwargs.get("extra_volumes"),
            extra_configs=kwargs.get("extra_configs"),
            extra_secrets=kwargs.get("extra_secrets"),
            deployment_mode=str(deployment_mode).strip(),
            storage=storage,
            dir_var_lib=str(dir_var_lib).strip(),
        )
        return [rendered]
