"""Lookup ``deploy_domains``: the clearnet domains the deploy serves on a host.

    {{ lookup('deploy_domains', group_names) }}

Args:
    group_names: every group of the host, after the swarm auto-placement.

Returns:
    The :func:`utils.preflight.domains.clearnet_domains` of the canonical
    domains of every role the deploy may run on the host.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.preflight.context import deploy_closure_context
from utils.preflight.domains import clearnet_domains


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "lookup('deploy_domains', group_names) expects exactly 1 term"
            )
        try:
            context = deploy_closure_context(self, variables, terms[0])
        except (TypeError, ValueError) as exc:
            raise AnsibleError(f"deploy_domains: {exc}") from exc
        return [
            clearnet_domains(
                [context.lookup("domains", role, []) for role in context.roles]
            )
        ]
