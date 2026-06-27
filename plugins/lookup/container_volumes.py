"""Lookup ``container_volumes(application_id, service)``: render the
per-service ``volumes:`` / ``configs:`` / ``secrets:`` block fed from
``meta/volumes.yml``. Output starts at column 0; callers add the indent.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.filter.container_volumes import (
    container_volumes as _render_container_volumes,
)
from utils.cache.applications import get_merged_applications
from utils.templating.ansible import _trust_as_template


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "container_volumes lookup requires exactly two terms: "
                "(application_id, service)"
            )
        application_id = str(terms[0]).strip()
        service = str(terms[1]).strip()
        if not application_id:
            raise AnsibleError(
                "container_volumes lookup: application_id must be non-empty"
            )
        if not service:
            raise AnsibleError("container_volumes lookup: service must be non-empty")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=templar,
        )

        render_jinja = None
        if templar is not None:
            # Closure captures the templar so mount-level `when:` Jinja
            # expressions are evaluated against the same context the
            # caller template sees, including `{% set %}` vars.
            def render_jinja(expr: str) -> Any:
                if not isinstance(expr, str):
                    return expr
                return templar.template(
                    _trust_as_template(expr),
                    fail_on_undefined=False,
                )

        rendered = _render_container_volumes(
            applications,
            application_id,
            service,
            extra_volumes=kwargs.get("extra_volumes"),
            extra_configs=kwargs.get("extra_configs"),
            extra_secrets=kwargs.get("extra_secrets"),
            render_jinja=render_jinja,
        )
        if rendered and not rendered.startswith("\n"):
            rendered = "\n" + rendered
        return [rendered]
