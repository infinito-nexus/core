"""Lookup `compose_replicas`: emit `replicas: <N>` only in swarm mode.

Single SPOT for swarm replica calculation across the repo.

Default value: `len(groups[application_id])` - one task per host in the
application's inventory group. Single-host inventories yield 1; multi-
host swarm inventories yield N matching the topology.

Override: pass an explicit value as the first term.

Examples:

    {{ lookup('compose_replicas') }}              # topology default
    {{ lookup('compose_replicas', 1) }}           # force replicas: 1
    {{ lookup('compose_replicas', N) }}           # force replicas: N

In compose mode the lookup returns the empty string because
docker-compose ignores `deploy.replicas`. Wrapping the emit in the
`deploy:` block remains the caller's responsibility - typically
`roles/sys-svc-container/templates/deploy.yml.j2`.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms and len(terms) > 1:
            raise AnsibleError(
                "compose_replicas lookup accepts at most one term: an explicit replicas override"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        raw_mode = vars_.get("DEPLOYMENT_MODE", "compose")
        if templar is not None:
            with contextlib.suppress(Exception):
                raw_mode = templar.template(raw_mode)

        if str(raw_mode).strip() != "swarm":
            return [""]

        if terms:
            replicas = terms[0]
        else:
            app_id = vars_.get("application_id")
            if templar is not None and app_id is not None:
                with contextlib.suppress(Exception):
                    app_id = templar.template(app_id)
            groups = vars_.get("groups", {}) or {}
            hosts = groups.get(app_id, []) if app_id else []
            replicas = len(hosts or [])

        try:
            n = int(replicas)
        except (TypeError, ValueError) as exc:
            raise AnsibleError(
                f"compose_replicas: cannot coerce '{replicas}' to int: {exc}"
            ) from exc
        if not terms and n < 1:
            n = 1
        return [f"replicas: {n}"]
