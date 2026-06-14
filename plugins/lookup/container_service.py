"""Lookup `container_service`: swarm-style service name for queries.

Sibling of `container_address` for service-level commands. While
`container_address` resolves to a runtime container ID for
`docker exec`, this lookup returns the addressable form for
`container service ps`, `container service logs`, and
`container ps --filter "label=com.docker.swarm.service.name=..."`.

Returns a string safe to embed unchanged into a shell command:

* Compose mode  - the bare service-key (e.g. `matomo`). Compose tracks
  services by container_name; the bare key matches `container ps -f
  name=matomo` and is the only useful form on a compose host.
* Swarm mode    - `<stack>_<service_key>`, matching how Docker Swarm
  names every service and how `container service ps` accepts them.
  The stack name is derived from ``application_id`` via the
  ``get_entity_name`` filter, mirroring how ``docker stack deploy``
  composes the stack name in
  ``sys-svc-compose/handlers/main.yml``.

Both terms (application_id, service_key) are required.
``services.<service_key>.name`` must exist in the resolved application
config.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.cache.applications import get_merged_applications
from utils.roles.entity_name import get_entity_name


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _resolve_bare_name(
    applications: dict[str, Any], application_id: str, service_key: str
) -> str:
    app = applications.get(application_id)
    if not isinstance(app, dict):
        raise AnsibleError(
            f"container_service: unknown application_id '{application_id}'"
        )
    services = app.get("services") or {}
    if not isinstance(services, dict):
        raise AnsibleError(
            f"container_service: '{application_id}' has no services dict"
        )
    entry = services.get(service_key)
    if not isinstance(entry, dict):
        raise AnsibleError(
            f"container_service: service '{service_key}' missing in "
            f"'{application_id}' services config"
        )
    name = entry.get("name")
    if not isinstance(name, str) or not name.strip():
        raise AnsibleError(
            f"container_service: services.{service_key}.name not set for "
            f"'{application_id}'"
        )
    return name.strip()


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms or len(terms) != 2:
            raise AnsibleError(
                "container_service lookup requires exactly two terms: "
                "application_id and service_key"
            )

        application_id = _as_str(terms[0])
        service_key = _as_str(terms[1])
        if not application_id:
            raise AnsibleError(
                "container_service: application_id must be a non-empty string"
            )
        if not service_key:
            raise AnsibleError(
                "container_service: service_key must be a non-empty string"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=templar,
        )

        bare_name = _resolve_bare_name(applications, application_id, service_key)

        raw_mode = vars_.get("DEPLOYMENT_MODE", "compose")
        if templar is not None:
            with contextlib.suppress(Exception):
                raw_mode = templar.template(raw_mode)
        deployment_mode = str(raw_mode).strip()

        if deployment_mode != "swarm":
            return [bare_name]

        stack_name = get_entity_name(application_id)
        if not stack_name:
            raise AnsibleError(
                f"container_service: cannot derive stack name from "
                f"application_id '{application_id}'"
            )

        # docker stack deploy creates service names as
        # `<stack>_<compose-yaml-service-key>`. The compose-side `name:`
        # field maps to `container_name` (compose) and is ignored by swarm.
        # Hence the swarm-addressable name uses the SERVICE KEY, not the
        # `services.<key>.name` value.
        return [f"{stack_name}_{service_key}"]
