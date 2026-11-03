"""Lookup ``network_ownership``: the docker networks of a host that do not
belong to their entity.

    {{ lookup('network_ownership', probe, group_names) }}

Args:
    probe: the registered result of ``container network inspect <every id>``.
    group_names: every group of the host, after the swarm auto-placement.

Returns:
    The messages of :func:`utils.networks.ownership.ownership_errors` for
    every role the deploy may run on the host
    (:func:`utils.roles.invocations.deploy_closure`) that declares
    ``networks.local.subnet``.
"""

from __future__ import annotations

import json
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils import PROJECT_ROOT
from utils.networks.ownership import ownership_errors
from utils.roles.entity.name import entity_name
from utils.roles.invocations import deploy_closure
from utils.roles.validation.invokable import types_from_group_names

_SUBNET_PATH = "networks.local.subnet"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "lookup('network_ownership', probe, group_names) expects exactly 2 terms"
            )
        probe, group_names = terms
        try:
            networks = json.loads(probe["stdout"])
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise AnsibleError(
                f"network_ownership: unparsable network inspect probe: {exc}"
            ) from exc

        groups = [str(group) for group in group_names]
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=templar
        ).run([], variables=vars_)[0]
        config = lookup_loader.get("config", loader=self._loader, templar=templar)
        try:
            roles = deploy_closure(
                applications,
                groups,
                project_root=PROJECT_ROOT,
                host_types=types_from_group_names(groups),
                group_names=groups,
            )
        except (TypeError, ValueError) as exc:
            raise AnsibleError(f"network_ownership: {exc}") from exc

        declared: dict[str, list[tuple[str, str]]] = {}
        for role in sorted(roles):
            subnet = str(
                config.run([role, _SUBNET_PATH, ""], variables=vars_)[0] or ""
            ).strip()
            if subnet:
                declared.setdefault(entity_name(role), []).append((role, subnet))
        return [ownership_errors(networks, declared)]
