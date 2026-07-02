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
sys-svc-compose during the constructor stage. It refuses to run on
non-manager nodes (exit 64) and reports clear errors when the service
has no running task (exit 65) or the task is not yet bound to a
container (exit 66).

Examples:

    # roles/web-app-X/vars/main.yml
    X_CONTAINER_ADDRESS: "{{ lookup('container_address', application_id, 'x') }}"

    # roles/web-app-X/tasks/01_setup.yml
    - shell: |
        container exec -i {{ X_CONTAINER_ADDRESS }} my-cli command

Both terms (application_id, service_key) are required.
``services.<service_key>.name`` must exist in the resolved application
config; the stack name is derived from ``application_id`` via the
``get_entity_name`` filter (matching how ``docker stack deploy``
names the stack in ``sys-svc-compose/handlers/main.yml``).
"""

from __future__ import annotations

import contextlib
import shlex
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.entity_name import get_entity_name


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _resolve_bare_name(
    applications: dict[str, Any], application_id: str, service_key: str
) -> str:
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
        entity = get_entity_name(application_id)
        if entity:
            entry = services.get(entity)
    if not isinstance(entry, dict):
        raise AnsibleError(
            f"container_address: service '{service_key}' missing in "
            f"'{application_id}' services config"
        )
    name = entry.get("name")
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

        bare_name = _resolve_bare_name(applications, application_id, service_key)

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

        if deployment_mode != "swarm":
            return [bare_name]

        stack_name = get_entity_name(application_id)
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

        return [
            f'"$({shlex.quote(bin_resolver)} '
            f'{shlex.quote(stack_name)} {shlex.quote(service_key)})"'
        ]
