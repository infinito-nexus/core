"""Lookup `container_address`: addressable form of a container for
`docker exec`, mode-aware.

Single SPOT for the swarm/compose split on container addressing.

Returns a string safe to embed unchanged into a shell `container exec`
command:

* Compose mode  - the bare service-key (e.g. `mattermost`). Compose
  sets `container_name:` explicitly so the name resolves locally.
* Swarm mode    - a shell subshell that resolves the running task's
  container ID at exec time, e.g.
  `"$(/usr/bin/resolve-container-id mattermost mattermost)"`. Swarm
  names every service ``<stack>_<key>`` and accepts no prefix matching;
  the helper composes that name from STACK and SERVICE_KEY args. The
  subshell defers resolution to the moment of exec, avoiding the stale
  ID and parse-time-failure pitfalls of returning a resolved value at
  vars-resolution time.

Because the lookup emits ``$(...)`` shell syntax, callers MUST use the
``ansible.builtin.shell`` module (not ``command``) for the surrounding
``container exec`` invocation. A companion lint rule enforces this.

The helper script `BIN_RESOLVE_CONTAINER_ID` is deployed by
sys-svc-compose during the constructor stage. It prints the container
of a running task on the local node on any node; without one it asks
the Swarm manager API and exits 64 on a non-manager node, 65 when the
service list fails or the service has no running task, 66 when the task
is not yet bound to a container and 67 when no service of that name
exists.

Examples::

    # roles/web-app-X/vars/main.yml
    X_CONTAINER_ADDRESS: "{{ lookup('container_address', application_id, 'x') }}"

    # roles/web-app-X/tasks/01_setup.yml
    - shell: |
        container exec -i {{ X_CONTAINER_ADDRESS }} my-cli command

Both terms (application_id, service_key) are required.
``services.<service_key>.name`` must exist in the resolved application
config; the stack name is derived from ``application_id`` via the
``entity_name`` filter (matching how ``docker stack deploy``
names the stack in ``sys-svc-compose/handlers/main.yml``).

Keyword ``instance``: an HA database instance from ``db_instances``. In
swarm mode the subshell then names that instance's service, or the
instance's per-host sidecar when ``service_key`` is a sidecar such as
``sentinel``.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.db.instances import DbInstancesError, instance_service
from utils.roles.db.primary import resolver_subshell
from utils.roles.entity.name import entity_name


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _service_entry(
    applications: dict[str, Any], application_id: str, service_key: str
) -> dict[str, Any]:
    app = applications.get(application_id)
    if not isinstance(app, dict):
        raise AnsibleError(
            f"container_address: unknown application_id '{application_id}'"
        )
    services = app.get("services") or {}
    if not isinstance(services, dict):
        raise AnsibleError(
            f"container_address: '{application_id}' has no services dict"
        )
    entry = services.get(service_key)
    if not isinstance(entry, dict) and service_key == "application":
        entity = entity_name(application_id)
        if entity:
            entry = services.get(entity)
    if not isinstance(entry, dict):
        raise AnsibleError(
            f"container_address: service '{service_key}' missing in "
            f"'{application_id}' services config"
        )
    return entry


def _resolve_bare_name(
    applications: dict[str, Any], application_id: str, service_key: str
) -> str:
    name = _service_entry(applications, application_id, service_key).get("name")
    if not isinstance(name, str) or not name.strip():
        raise AnsibleError(
            f"container_address: services.{service_key}.name not set for "
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
                "container_address lookup requires exactly two terms: "
                "application_id and service_key"
            )

        application_id = _as_str(terms[0])
        service_key = _as_str(terms[1])
        if not application_id:
            raise AnsibleError(
                "container_address: application_id must be a non-empty string"
            )
        if not service_key:
            raise AnsibleError(
                "container_address: service_key must be a non-empty string"
            )

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        raw_mode = vars_.get("DEPLOYMENT_MODE", "compose")
        if templar is not None:
            with contextlib.suppress(Exception):
                raw_mode = templar.template(raw_mode)
        deployment_mode = str(raw_mode).strip()

        mode_force = vars_.get("compose_mode_force", "")
        if templar is not None:
            with contextlib.suppress(Exception):
                mode_force = templar.template(mode_force)
        deployment_mode = _as_str(mode_force) or deployment_mode

        instance = kwargs.get("instance")
        if instance and deployment_mode == "swarm":
            _service_entry(applications, application_id, service_key)
        else:
            bare_name = _resolve_bare_name(applications, application_id, service_key)
        if deployment_mode != "swarm":
            return [bare_name]

        stack_name = entity_name(application_id)
        if not stack_name:
            raise AnsibleError(
                f"container_address: cannot derive stack name from "
                f"application_id '{application_id}'"
            )

        bin_resolver = vars_.get("BIN_RESOLVE_CONTAINER_ID")
        if templar is not None and bin_resolver is not None:
            with contextlib.suppress(Exception):
                bin_resolver = templar.template(bin_resolver)
        bin_resolver = _as_str(bin_resolver) or "/usr/bin/resolve-container-id"

        target = service_key
        if instance:
            try:
                target = instance_service(application_id, instance, service_key)
            except (DbInstancesError, KeyError, TypeError) as exc:
                raise AnsibleError(f"container_address: {exc}") from exc

        return [resolver_subshell(bin_resolver, stack_name, target)]
