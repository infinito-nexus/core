"""Mode-aware nginx ``proxy_pass`` directive renderer (compose/swarm), SPOT.

Trip-wire: the swarm oauth2 endpoint must forward ``$uri$is_args$args``, not
``$request_uri`` — during ``error_page 401 = /oauth2/start`` the original
``$request_uri`` stays ``/`` and oauth2-proxy 403s instead of redirecting.
"""

from __future__ import annotations

import re
from typing import Any

from utils.roles.applications.config import get
from utils.roles.entity.name import get_entity_name

_REGEX_OR_NAMED_LOCATION = re.compile(r"^[@~]")
_LOCATION_MODIFIER = re.compile(r"^(?:=|\^~)\s*")
_UPSTREAM_VAR = "proxy_pass_upstream"


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def resolve_upstream(
    applications: dict[str, Any],
    application_id: str,
    service_key: str,
    port_kind: str,
    deployment_mode: str,
    local_port: str = "",
    internal_port: str = "",
    host_gateway: bool = False,
) -> str:
    """Upstream ``host:port``: compose ``127.0.0.1:<local>``; swarm
    ``<entity>:<internal>`` (shared-overlay alias) for the app frontend, or
    ``<entity>_<service_key>:<internal>`` for named sidecars (sso-proxy).
    A ``host_gateway`` app runs node-local under swarm and publishes its
    local port to the host, so the overlay-attached proxy reaches it at
    ``host.docker.internal:<local>`` via the host gateway (the caller sets
    this off the real DEPLOYMENT_MODE, since such apps force a compose-style
    render). Missing swarm internal port hard-fails."""
    entity = get_entity_name(application_id)
    if not entity:
        raise ValueError(
            f"resolve_upstream: cannot derive entity from {application_id!r}"
        )
    service_key = _as_str(service_key) or entity

    def _config_port(scope: str) -> str:
        return _as_str(
            get(
                applications=applications,
                application_id=application_id,
                config_path=f"services.{entity}.ports.{scope}.{port_kind}",
                strict=False,
                default="",
            )
        )

    if host_gateway or deployment_mode != "swarm":
        port = _as_str(local_port) or _config_port("local")
        if not port:
            raise ValueError(
                f"resolve_upstream: no local port for {application_id!r} "
                f"(services.{entity}.ports.local.{port_kind})"
            )
        if host_gateway:
            return f"host.docker.internal:{port}"
        host = (
            _as_str(
                get(
                    applications=applications,
                    application_id=application_id,
                    config_path=f"services.{entity}.upstream_host",
                    strict=False,
                    default="",
                )
            )
            or "127.0.0.1"
        )
        return f"{host}:{port}"

    port = _as_str(internal_port) or _config_port("internal")
    if not port:
        raise ValueError(
            f"resolve_upstream: swarm upstream for {application_id!r} needs "
            f"services.{entity}.ports.internal.{port_kind} (or internal_port=)"
        )
    if service_key == entity:
        return f"{entity}:{port}"
    return f"{entity}_{service_key}:{port}"


def _compose_suffix(tail: str, location: str) -> str:
    if tail == "request":
        loc = location.strip()
        if _REGEX_OR_NAMED_LOCATION.match(loc):
            return ""
        return _LOCATION_MODIFIER.sub("", loc)
    if tail.startswith("/"):
        return tail
    return ""


def _swarm_tail(tail: str) -> str:
    if tail == "oauth2":
        return "$uri$is_args$args"
    if tail.startswith("/"):
        return tail
    return "$request_uri"


def render_proxy_pass(
    authority: str,
    deployment_mode: str,
    tail: str = "request",
    location: str = "/",
    host_gateway: bool = False,
) -> str:
    """``proxy_pass`` directive; swarm prepends a ``set`` line (request-time DNS).

    A ``host_gateway`` upstream resolves through ``host.docker.internal`` in
    ``/etc/hosts`` (host gateway), which the request-time ``resolver`` cannot
    see, so it renders as a literal directive like compose."""
    if not authority:
        raise ValueError("render_proxy_pass: authority must be non-empty")

    if deployment_mode == "swarm" and not host_gateway:
        return (
            f'set ${_UPSTREAM_VAR} "{authority}";\n'
            f"    proxy_pass http://${_UPSTREAM_VAR}{_swarm_tail(tail)};"
        )
    return f"proxy_pass http://{authority}{_compose_suffix(tail, location)};"
