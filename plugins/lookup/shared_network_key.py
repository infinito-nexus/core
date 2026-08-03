"""Lookup `shared_network_key`: the compose networks key of the pre-created
``<entity>`` network of a role.

Docker compose stores that key in the ``com.docker.compose.network`` label of
every network it owns, so a caller pre-creating the network out of band has to
stamp the same value or compose will resolve the project's networks against a
claim the rendered file does not make. The key is derived from
``utils.networks.render``, which renders the file itself, so the two cannot
drift.

Examples:

    - name: create the shared network
      ansible.builtin.command:
        argv:
          - container
          - network
          - create
          - --label
          - "com.docker.compose.network={{ lookup('shared_network_key', role_id) }}"
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import build_context, resolve_var
from utils.networks.render import shared_network_compose_key
from utils.roles.entity.name import get_entity_name


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "shared_network_key lookup requires exactly one term: application_id"
            )

        ctx = build_context(self, variables)
        application_id = str(resolve_var(ctx.templar, terms[0]))

        return [
            shared_network_compose_key(
                application_id=application_id,
                deployment_mode=ctx.deployment_mode,
                registry=ctx.registry,
                get_entity_name=get_entity_name,
                lookup_config=ctx.lookup_config,
                lookup_database=ctx.lookup_database,
                node_local=bool(kwargs.get("node_local", False)),
            )
        ]
