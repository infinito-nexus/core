"""Lookup `db_endpoint`: the HAProxy write endpoint of a central engine.

    lookup('db_endpoint')                                  # current application_id
    lookup('db_endpoint', 'svc-db-redis', check_user=REDIS_HAPROXY_CHECK_USER,
           check_password=REDIS_HAPROXY_CHECK_PASSWORD)
    lookup('db_endpoint', 'svc-db-openldap', field='sysctls')

Without ``field`` it returns the ``haproxy.cfg`` text from
``utils.roles.db.endpoint.render_haproxy_cfg`` for the engine's HA instance
list and raises when the engine renders its standalone form. ``field='sysctls'``
returns the endpoint container's sysctls: TCP keepalive timings and, for a port
below 1024, the unprivileged-port start the non-root HAProxy needs.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.lookup.db_instances import LookupModule as DbInstancesLookup
from utils.roles.db.endpoint import (
    DbEndpointError,
    endpoint_settings,
    endpoint_sysctls,
    render_haproxy_cfg,
)
from utils.roles.db.instances import FORM_HA, DbInstancesError, engine_word

_FIELDS = (None, "sysctls")


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) > 1:
            raise AnsibleError(
                "db_endpoint: expected at most 1 term, the engine application_id"
            )
        field = kwargs.get("field")
        if field not in _FIELDS:
            raise AnsibleError(f"db_endpoint: field must be one of {_FIELDS}")
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        app_id = terms[0] if terms else vars_.get("application_id")
        if templar is not None:
            with contextlib.suppress(Exception):
                app_id = templar.template(app_id)
        app_id = str(app_id)

        applications = lookup_loader.get(
            "applications",
            loader=getattr(self, "_loader", None),
            templar=templar,
        ).run([], variables=vars_)[0]
        try:
            entity = engine_word(app_id)
            ports = applications[app_id]["services"][entity]["ports"]["internal"]
        except DbInstancesError as exc:
            raise AnsibleError(str(exc)) from exc
        except (KeyError, TypeError) as exc:
            raise AnsibleError(
                f"db_endpoint: {app_id} has no services.<engine>.ports.internal in its "
                "merged configuration"
            ) from exc
        try:
            settings = endpoint_settings(app_id, ports)
        except (DbEndpointError, DbInstancesError) as exc:
            raise AnsibleError(str(exc)) from exc

        if field == "sysctls":
            return [endpoint_sysctls(settings["port"])]

        instances_lookup = DbInstancesLookup()
        instances_lookup._templar = templar
        db = instances_lookup.run([app_id], variables=vars_)[0]
        if db["form"] != FORM_HA:
            raise AnsibleError(
                f"db_endpoint: {app_id} renders its standalone form, no write endpoint"
            )
        try:
            return [
                render_haproxy_cfg(
                    settings,
                    db["instances"],
                    check_user=kwargs.get("check_user"),
                    check_password=kwargs.get("check_password"),
                )
            ]
        except DbEndpointError as exc:
            raise AnsibleError(str(exc)) from exc
