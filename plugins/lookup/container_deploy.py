"""Lookup ``container_deploy``: emit the swarm ``deploy:`` head — the replica
count plus, for a role whose primary entity declares one, the placement
constraint. Renders nothing outside swarm mode, so callers need no mode guard
of their own.

    {{ lookup('container_deploy') | indent(4) }}                # topology default
    {{ lookup('container_deploy', replicas=1) | indent(4) }}    # single-writer sidecar
    {{ lookup('container_deploy', replicas=n) | indent(4) }}    # explicit; '' = default

Callers that also need ``update_config``, ``restart_policy`` or ``resources``
append them under the same key.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.meta_lookup import get_role_placement


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms:
            raise AnsibleError(
                "container_deploy lookup takes no positional terms; "
                "pass the replica count as replicas=<n>"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        mode = (
            vars_.get("compose_mode")
            or vars_.get("compose_mode_force")
            or vars_.get("DEPLOYMENT_MODE", "compose")
        )
        if templar is not None:
            with contextlib.suppress(Exception):
                mode = templar.template(mode)
        if str(mode).strip() != "swarm":
            return [""]

        application_id = vars_.get("application_id")
        if templar is not None and application_id is not None:
            with contextlib.suppress(Exception):
                application_id = templar.template(application_id)
        if not application_id:
            raise AnsibleError(
                "container_deploy lookup: application_id is required in variables"
            )

        replicas_override = kwargs.get("replicas", "")
        override = [replicas_override] if str(replicas_override) != "" else []
        replicas = lookup_loader.get(
            "compose_replicas", loader=self._loader, templar=templar
        ).run(override, variables={**vars_, "DEPLOYMENT_MODE": "swarm"})[0]

        lines = ["deploy:", f"  {replicas}"]
        placement = get_role_placement(str(application_id))
        if placement:
            lines += [
                "  placement:",
                "    constraints:",
                f"      - node.role == {placement}",
            ]
        return ["\n".join(lines)]
