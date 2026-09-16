"""Lookup `container_ports`: build a compose ``ports:`` block from declared ports.

Single SPOT for every published port in the repo. A term is either the short
list form or the dict form; pass one or more.

List form, unchanged::

    {{ lookup('container_ports',
              ['gitea', 'http', DOCKER_BIND_HOST],
              ['gitea', 'ssh']) | indent(4) }}

produces::

    ports:
      - "<DOCKER_BIND_HOST>:<services.gitea.ports.local.http>:<...internal.http>"
      - "<services.gitea.ports.public.ssh>:<services.gitea.ports.internal.ssh>"

The published (host) port is ``ports.local.<proto>`` when declared, else
``ports.public.<proto>``; the container port is ``ports.internal.<proto>``.

Dict form, for the shapes the list form cannot express::

    {{ lookup('container_ports',
              {'service': 'coturn', 'protocol': 'stun_turn',
               'transport': ['udp', 'tcp'], 'container': 'same'},
              {'service': 'coturn', 'protocol': 'relay', 'transport': 'udp',
               'container': 'same'},
              {'service': 'openresty', 'protocol': 'http', 'mode': 'host'},
              {'service': 'funkwhale', 'protocol': 'api',
               'publish': 'ephemeral'}) | indent(4) }}

Keys:

``service``, ``protocol``
    Required, as in the list form.
``ip``
    Host address to bind to; omit to publish on every interface.
``transport``
    ``tcp``, ``udp``, or a list of both. One list item per transport. Omit for
    compose's own default, which publishes no suffix.
``container``
    ``internal`` (default) reads ``ports.internal.<proto>``; ``same`` reuses the
    published port, for services that cannot remap (STUN/TURN, media relays).
``mode``
    ``ingress`` (default) emits the short ``"host:published:container"`` string;
    ``host`` emits the long block with ``mode: host``, which is what an edge
    role needs in swarm so the client address survives the hop.
``publish``
    ``ephemeral`` publishes the container port on a host port docker picks, for
    a service addressed only through the compose network.

A declared value that is a ``{start, end}`` mapping renders as ``start-end`` on
both sides, so a relay range needs no special term.

``application_id`` is read from the play variables unless given as
``application_id=``. ``key='expose'`` names the block instead of ``ports``, for
Discourse's launcher file, whose ``expose:`` list is what becomes ``docker run
-p`` there.
"""

from __future__ import annotations

import contextlib
from collections.abc import Mapping
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase
from ansible.template import trust_as_template

from utils.roles.applications.config import get

_TERM_KEYS = frozenset(
    {"service", "protocol", "ip", "transport", "container", "mode", "publish"}
)
_TRANSPORTS = ("tcp", "udp")
_CONTAINER_SOURCES = ("internal", "same")
_MODES = ("ingress", "host")


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _rendered(value: Any) -> str:
    """A declared port value as compose writes it, ranges included."""
    if isinstance(value, Mapping):
        start, end = value.get("start"), value.get("end")
        if start is None or end is None:
            return ""
        return f"{_as_str(start)}-{_as_str(end)}"
    return _as_str(value)


def _transports_of(term: Mapping) -> list[str]:
    declared = term.get("transport")
    if declared is None:
        return [""]
    wanted = [declared] if isinstance(declared, str) else list(declared)
    for transport in wanted:
        if transport not in _TRANSPORTS:
            raise AnsibleError(
                f"container_ports: transport must be one of {_TRANSPORTS}, "
                f"got {transport!r}"
            )
    return wanted


def _normalised(term: Any) -> dict[str, Any]:
    """One term as a dict, accepting the legacy list form."""
    if isinstance(term, (list, tuple)):
        if len(term) not in (2, 3):
            raise AnsibleError(
                "container_ports: a list term must be [service_name, protocol] "
                f"or [service_name, protocol, host_ip], got {term!r}"
            )
        term = {
            "service": term[0],
            "protocol": term[1],
            **({"ip": term[2]} if len(term) == 3 else {}),
        }
    if not isinstance(term, Mapping):
        raise AnsibleError(
            f"container_ports: each term must be a list or a mapping, got {term!r}"
        )
    unknown = set(term) - _TERM_KEYS
    if unknown:
        raise AnsibleError(
            f"container_ports: unknown term key(s) {sorted(unknown)}; "
            f"valid keys are {sorted(_TERM_KEYS)}"
        )
    normalised = {
        "service": _as_str(term.get("service")),
        "protocol": _as_str(term.get("protocol")),
        "ip": _as_str(term.get("ip")),
        "transport": term.get("transport"),
        "container": _as_str(term.get("container")) or "internal",
        "mode": _as_str(term.get("mode")) or "ingress",
        "publish": _as_str(term.get("publish")),
    }
    if not normalised["service"] or not normalised["protocol"]:
        raise AnsibleError("container_ports: service and protocol must be non-empty")
    if normalised["container"] not in _CONTAINER_SOURCES:
        raise AnsibleError(
            f"container_ports: container must be one of {_CONTAINER_SOURCES}, "
            f"got {normalised['container']!r}"
        )
    if normalised["mode"] not in _MODES:
        raise AnsibleError(
            f"container_ports: mode must be one of {_MODES}, got {normalised['mode']!r}"
        )
    if normalised["publish"] and normalised["publish"] != "ephemeral":
        raise AnsibleError(
            "container_ports: publish accepts only 'ephemeral', "
            f"got {normalised['publish']!r}"
        )
    if normalised["mode"] == "host" and normalised["ip"]:
        raise AnsibleError(
            "container_ports: mode 'host' binds the node's own interface and "
            "takes no ip"
        )
    return normalised


def _short_line(term: Mapping, published: str, container: str, transport: str) -> str:
    suffix = f"/{transport}" if transport else ""
    if term["publish"] == "ephemeral":
        return f'  - "{container}{suffix}"'
    head = f"{term['ip']}:" if term["ip"] else ""
    return f'  - "{head}{published}:{container}{suffix}"'


def _host_lines(published: str, container: str, transport: str) -> list[str]:
    return [
        f"  - target: {container}",
        f"    published: {published}",
        f"    protocol: {transport or 'tcp'}",
        "    mode: host",
    ]


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
                "expects one or more terms"
            )
        parsed = [_normalised(term) for term in terms]

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
            value = _rendered(
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

        block_key = _as_str(kwargs.get("key")) or "ports"
        if block_key not in ("ports", "expose"):
            raise AnsibleError(
                f"container_ports: key must be 'ports' or 'expose', got {block_key!r}"
            )
        lines = [f"{block_key}:"]
        for term in parsed:
            service, protocol = term["service"], term["protocol"]
            published = _port(service, "local", protocol, required=False) or _port(
                service, "public", protocol, required=term["publish"] != "ephemeral"
            )
            if term["container"] == "same":
                container = published
            else:
                container = _port(service, "internal", protocol, required=True)
            for transport in _transports_of(term):
                if term["mode"] == "host":
                    lines.extend(_host_lines(published, container, transport))
                else:
                    lines.append(_short_line(term, published, container, transport))
        return ["\n".join(lines)]
