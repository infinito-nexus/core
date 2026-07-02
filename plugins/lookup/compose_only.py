"""Lookup `compose_only`: emit a `key: "<value>"` YAML pair only in
compose mode; emit nothing under swarm.

A single SPOT for every service-level YAML key that is structurally
incompatible with `docker stack deploy` and must therefore be omitted
when DEPLOYMENT_MODE == 'swarm'. Currently used for:

* `container_name` — swarm rejects it alongside `deploy.replicas > 1`
  ("can't set container_name and X as container name must be unique").
* `pull_policy` — swarm rejects it as "Additional property pull_policy
  is not allowed" (compose-only extension).

Both call sites look identical:

    {{ lookup('compose_only', 'container_name', MY_CONTAINER) }}
    {{ lookup('compose_only', 'pull_policy', 'never') }}

The value is always double-quoted in the output. That makes the emit
safe for YAML edge cases like `restart: no` (bare `no` would otherwise
parse as a boolean) without burdening the caller with quoting rules.
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
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "compose_only lookup requires exactly two terms: the key and the value"
            )
        key = str(terms[0]).strip()
        value = str(terms[1])
        if not key:
            raise AnsibleError("compose_only lookup: key term must be non-empty")

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        raw_mode = vars_.get("DEPLOYMENT_MODE", "compose")
        templar = getattr(self, "_templar", None)
        if templar is not None:
            with contextlib.suppress(Exception):
                raw_mode = templar.template(raw_mode)

        if str(raw_mode).strip() == "swarm":
            return [""]
        return [f'{key}: "{value}"']
