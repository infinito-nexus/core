"""Lookup `compose_volumes`: render the top-level `volumes:` block for
a given application_id.

Single SPOT replacement for the previous

    {{ lookup('applications') | compose_volumes(application_id) }}

pipe pattern. The lookup auto-wires the `applications` registry, the
DEPLOYMENT_MODE, and the `storage` mapping from the templating context
so call sites only pass what genuinely varies per service.

Call sites:

    {{ lookup('compose_volumes', application_id) }}
    {{ lookup('compose_volumes', application_id, extra_volumes={'data': {'name': MY_VOL}}) }}

`deployment_mode` and `storage` may still be overridden per call when a
template needs a non-default rendering, but the common case is the
auto-wired defaults from `DEPLOYMENT_MODE` and the `storage` group var.

The underlying rendering function lives in `plugins/filter/compose_volumes.py`
(kept as an importable utility); only the Jinja filter registration was
removed so the deprecated pipe form fails fast.
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

        if templar is not None:
            with contextlib.suppress(Exception):
                deployment_mode = templar.template(deployment_mode)
            with contextlib.suppress(Exception):
                storage = templar.template(storage)

        rendered = _render_compose_volumes(
            applications,
            application_id,
            extra_volumes=kwargs.get("extra_volumes"),
            deployment_mode=str(deployment_mode).strip(),
            storage=storage,
        )
        return [rendered]
