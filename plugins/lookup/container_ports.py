"""Lookup `container_ports`: build a compose ``ports:`` publish block from
``[service_name, protocol]`` or ``[service_name, protocol, host_ip]`` terms.

Single SPOT replacing the repeated, verbose port lookups. Each term is a
two- or three-element list; pass one or more. The optional third element is
the host IP to bind that port to; omit it to publish on every interface:

    {{ lookup('container_ports',
              ['gitea', 'http', DOCKER_BIND_HOST],
              ['gitea', 'ssh']) | indent(4) }}

produces

    ports:
      - "<DOCKER_BIND_HOST>:<services.gitea.ports.local.http>:<services.gitea.ports.internal.http>"
      - "<services.gitea.ports.public.ssh>:<services.gitea.ports.internal.ssh>"

Per term the published (host) port is ``services.<svc>.ports.local.<proto>``
when declared, else ``services.<svc>.ports.public.<proto>``; the container
port is always ``services.<svc>.ports.internal.<proto>``. A third element
prefixes ``<host_ip>:``; without it the port binds to all interfaces. This
makes every mapping expressible, including binds to a specific public IP
(e.g. ``['mailu', 'smtp', MAILU_IP4_PUBLIC]``).

``application_id`` is read from the play variables unless given as ``application_id=``.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import trust_as_template

from utils.roles.applications.config import get


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        if kwargs.get("ip"):
            raise AnsibleError(
                "container_ports: the 'ip=' keyword is removed; pass the host ip "
                "as the optional third element of each term, e.g. "
                "['gitea', 'http', DOCKER_BIND_HOST]"
            )
        if not terms:
            raise AnsibleError(
                "lookup('container_ports', [service_name, protocol[, host_ip]], ...) "
                "expects one or more [service_name, protocol] terms"
            )
        triples: list[tuple[str, str, str]] = []
        for term in terms:
            if not (isinstance(term, (list, tuple)) and len(term) in (2, 3)):
                raise AnsibleError(
                    "container_ports: each term must be a [service_name, protocol] "
                    f"or [service_name, protocol, host_ip] list, got {term!r}"
                )
            service, protocol = _as_str(term[0]), _as_str(term[1])
            host = _as_str(term[2]) if len(term) == 3 else ""
            if not service or not protocol:
                raise AnsibleError(
                    "container_ports: service_name and protocol must be non-empty"
                )
            triples.append((service, protocol, host))

        templar = getattr(self, "_templar", None)
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        application_id = _as_str(
            kwargs.get("application_id") or variables.get("application_id")
        )
        if templar is not None and "{{" in application_id:
            with contextlib.suppress(Exception):
                application_id = _as_str(
                    templar.template(trust_as_template(application_id))
                )
        if not application_id:
            raise AnsibleError(
                "container_ports: no application_id in the play vars; pass "
                "application_id= explicitly"
            )

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=variables)[0]

        def _port(service: str, scope: str, protocol: str, *, required: bool) -> str:
            value = _as_str(
                get(
                    applications=applications,
                    application_id=application_id,
                    config_path=f"services.{service}.ports.{scope}.{protocol}",
                    strict=False,
                    default="",
                )
            )
            if not value and required:
                raise AnsibleError(
                    f"container_ports: services.{service}.ports.{scope}.{protocol} "
                    f"is not set for '{application_id}'"
                )
            return value

        lines = ["ports:"]
        for service, protocol, host in triples:
            internal = _port(service, "internal", protocol, required=True)
            published = _port(service, "local", protocol, required=False) or _port(
                service, "public", protocol, required=True
            )
            if host:
                lines.append(f'  - "{host}:{published}:{internal}"')
            else:
                lines.append(f'  - "{published}:{internal}"')
        return ["\n".join(lines)]
