"""Lookup `db_instances`: the instance list of a central database engine.

    lookup('db_instances')                       # current application_id
    lookup('db_instances', 'svc-db-postgres')
    lookup('db_instances', 'svc-db-postgres', legacy_volume_host='mgr-01')
    lookup('db_instances', coordination_store_needed=true)   # bool
    lookup('db_instances', coordination_store=true)          # role id of the store
    lookup('db_instances', ha_engines=true)                  # [role id], sorted
    lookup('db_instances', primary_probes=true)              # [{"name", "src"}]
    lookup('db_instances', 'svc-db-openldap', exposure_conflicts=true)  # [str]

An empty engine group falls back to the group its meta declares as
``ha.host_group``.

Returns ``{"form", "instances", "warnings", "ha"}`` from
``utils.roles.db.instances.build_instances``; warnings are also displayed.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.utils.display import Display

from plugins.lookup.tor_reachable import is_reachable
from utils.roles.db.instances import (
    SWARM_NODE_GROUP,
    DbInstancesError,
    build_instances,
    coordination_store,
    coordination_store_needed,
    engine_hosts,
    ha_engines,
    ha_exposure_conflicts,
    primary_probes,
)

display = Display()


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict]:
        terms = terms or []
        if len(terms) > 1:
            raise AnsibleError(
                "db_instances: expected at most 1 term, the engine application_id"
            )
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        def _templated(value):
            if templar is not None:
                with contextlib.suppress(Exception):
                    return templar.template(value)
            return value

        app_id = str(_templated(terms[0] if terms else vars_.get("application_id")))
        mode = str(_templated(vars_.get("DEPLOYMENT_MODE", "compose"))).strip()
        groups = vars_.get("groups", {}) or {}
        try:
            if kwargs.get("coordination_store_needed"):
                return [coordination_store_needed(groups, mode)]
            if kwargs.get("coordination_store"):
                return [coordination_store()]
            if kwargs.get("ha_engines"):
                return [sorted(ha_engines())]
            if kwargs.get("primary_probes"):
                return [primary_probes()]
            if kwargs.get("exposure_conflicts"):
                applications = lookup_loader.get(
                    "applications",
                    loader=getattr(self, "_loader", None),
                    templar=templar,
                ).run([], variables=vars_)[0]
                return [
                    ha_exposure_conflicts(
                        app_id,
                        applications.get(app_id) or {},
                        tor_reachable=is_reachable(applications, app_id),
                    )
                ]
        except DbInstancesError as exc:
            raise AnsibleError(str(exc)) from exc
        try:
            result = build_instances(
                app_id,
                engine_hosts(app_id, groups),
                deployment_mode=mode,
                swarm_nodes=list(groups.get(SWARM_NODE_GROUP, []) or []),
                legacy_volume_host=kwargs.get("legacy_volume_host"),
            )
        except DbInstancesError as exc:
            raise AnsibleError(str(exc)) from exc
        for warning in result["warnings"]:
            display.warning(warning)
        return [result]
