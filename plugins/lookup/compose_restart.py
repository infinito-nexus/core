"""Lookup `compose_restart`: emit `restart: <policy>` only in compose mode.

In swarm mode the `restart:` top-level service key is silently ignored
because swarm replaces it with `deploy.restart_policy` (rendered by
`roles/sys-svc-container/templates/deploy.yml.j2`). Emitting `restart:`
under swarm produces an "Ignoring unsupported options" warning at
`docker stack deploy` time and double-declares the intent.

Default call site:

    {{ lookup('compose_restart') }}

resolves to the global `DOCKER_RESTART_POLICY` from
`group_vars/all/00_general.yml`. That covers every caller whose intent
is "use the operator-wide default policy".

When a template needs a per-call override (either via Jinja-scope
``{% set docker_restart_policy = '...' %}`` or a hardcoded literal),
the caller passes the policy explicitly:

    {{ lookup('compose_restart', docker_restart_policy | default(DOCKER_RESTART_POLICY)) }}
    {{ lookup('compose_restart', 'on-failure') }}

The override path lives at the caller because Jinja-scope `{% set %}`
bindings are visible only in the rendering template, never in the
Ansible variable context that the lookup sees.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

_DEFAULT_POLICY = "unless-stopped"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if terms and len(terms) > 1:
            raise AnsibleError(
                "compose_restart lookup accepts at most one term: an explicit policy override"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        raw_mode = vars_.get("DEPLOYMENT_MODE", "compose")
        templar = getattr(self, "_templar", None)
        if templar is not None:
            with contextlib.suppress(Exception):
                raw_mode = templar.template(raw_mode)

        if str(raw_mode).strip() == "swarm" and not bool(
            kwargs.get("node_local", False)
        ):
            return [""]

        if terms:
            policy = terms[0]
        else:
            policy = vars_.get("DOCKER_RESTART_POLICY", _DEFAULT_POLICY)
            if templar is not None:
                with contextlib.suppress(Exception):
                    policy = templar.template(policy)

        return [f'restart: "{policy}"']
