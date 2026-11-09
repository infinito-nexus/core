"""Mode-aware nginx ``proxy_pass`` directive renderer and the addresses its
requests reach an application from (compose/swarm), SPOT.

Trip-wire: the swarm oauth2 endpoint must forward ``$uri$is_args$args``, not
``$request_uri`` — during the ``error_page 401 = @oauth2_start`` jump the original
``$request_uri`` stays ``/`` and oauth2-proxy 403s instead of redirecting.

Trip-wire: a compose ``request`` tail renders no URI part. With one, nginx
forwards the normalized, percent-decoded URI (``%3A`` becomes ``:``), so a
signed request such as Matrix federation (``/v2/invite/!room%3Aserver/...``)
fails its signature check upstream.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils.networks.address import subnet_gateway
from utils.roles.applications.config import get
from utils.roles.entity.name import entity_name

if TYPE_CHECKING:
    from collections.abc import Callable

_UPSTREAM_VAR = "proxy_pass_upstream"
REVERSE_PROXY_APPLICATION_ID = "svc-prx-openresty"
UPSTREAM_SCHEMES = ("http", "https")


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def resolve_upstream_scheme(
    applications: dict[str, Any],
    application_id: str,
    service_key: str,
) -> str:
    """Scheme the reverse proxy speaks to an application's own frontend.

    Args:
        applications: the ``lookup('applications')`` map.
        application_id: the proxied application.
        service_key: the service the location reaches; empty means the frontend.

    Returns:
        ``services.<entity>.upstream_scheme`` for the frontend, ``http`` when it
        is unset and for every sidecar (sso-proxy, logout), which stay plaintext.

    Raises:
        ValueError: the declared scheme is neither ``http`` nor ``https``.
    """
    entity = entity_name(application_id)
    if (_as_str(service_key) or entity) != entity:
        return UPSTREAM_SCHEMES[0]
    scheme = (
        _as_str(
            get(
                applications=applications,
                application_id=application_id,
                config_path=f"services.{entity}.upstream_scheme",
                strict=False,
                default="",
            )
        ).lower()
        or UPSTREAM_SCHEMES[0]
    )
    if scheme not in UPSTREAM_SCHEMES:
        raise ValueError(
            f"resolve_upstream_scheme: services.{entity}.upstream_scheme of "
            f"{application_id!r} is {scheme!r}, expected one of {UPSTREAM_SCHEMES}"
        )
    return scheme


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
    entity = entity_name(application_id)
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


def _compose_suffix(tail: str) -> str:
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
    host_gateway: bool = False,
    scheme: str = UPSTREAM_SCHEMES[0],
) -> str:
    """``proxy_pass`` directive; swarm prepends a ``set`` line (request-time DNS).

    A ``host_gateway`` upstream resolves through ``host.docker.internal`` in
    ``/etc/hosts`` (host gateway), which the request-time ``resolver`` cannot
    see, so it renders as a literal directive like compose.

    ``scheme`` comes from :func:`resolve_upstream_scheme`; an ``https``
    upstream is reached without certificate verification, nginx's
    ``proxy_ssl_verify off`` default, because the hop is the loopback or the
    container network, never a public route."""
    if not authority:
        raise ValueError("render_proxy_pass: authority must be non-empty")
    if scheme not in UPSTREAM_SCHEMES:
        raise ValueError(
            f"render_proxy_pass: scheme {scheme!r} not in {UPSTREAM_SCHEMES}"
        )

    if deployment_mode == "swarm" and not host_gateway:
        return (
            f'set ${_UPSTREAM_VAR} "{authority}";\n'
            f"    proxy_pass {scheme}://${_UPSTREAM_VAR}{_swarm_tail(tail)};"
        )
    return f"proxy_pass {scheme}://{authority}{_compose_suffix(tail)};"


def render_stream_proxy_pass(
    authority: str, deployment_mode: str, host_gateway: bool
) -> str:
    """``proxy_pass`` directive of an nginx ``stream`` server.

    Args:
        authority: upstream ``host:port`` from :func:`resolve_upstream`.
        deployment_mode: ``compose`` or ``swarm``, after any per-role override.
        host_gateway: the upstream resolves through ``host.docker.internal``.

    Returns:
        Under swarm a ``set`` line and a ``proxy_pass`` of that variable, so the
        stream ``resolver`` looks the upstream up per connection; otherwise
        the literal directive.
    """
    if not authority:
        raise ValueError("render_stream_proxy_pass: authority must be non-empty")
    if deployment_mode == "swarm" and not host_gateway:
        return f'set ${_UPSTREAM_VAR} "{authority}";\n    proxy_pass ${_UPSTREAM_VAR};'
    return f"proxy_pass {authority};"


def proxy_hops(
    application_id: str,
    deployment_mode: str,
    network_roles: Callable[[str], list[str]],
    subnets: Callable[[list[str]], list[str]],
) -> list[str]:
    """Addresses the reverse proxy's requests reach ``application_id`` from.

    Args:
        application_id: the proxied application.
        deployment_mode: ``compose`` or ``swarm``, after any per-role override.
        network_roles: role id to the provider roles whose networks it joins.
        subnets: role ids to their ``networks.local.subnet``, in order.

    Returns:
        Under compose the gateway of the application's own network and of
        every network it joins: the proxy runs on the host network and reaches
        a published port, which Docker forwards from the gateway of whichever
        of those networks it routes the container through. Under swarm the
        subnets of the overlays the application shares with the proxy, which
        reaches it from its task address there.

    Raises:
        ValueError: under swarm the application shares no overlay with the
            proxy.
    """
    if deployment_mode != "swarm":
        roles = list(dict.fromkeys([application_id, *network_roles(application_id)]))
        return list(dict.fromkeys(subnet_gateway(subnet) for subnet in subnets(roles)))
    proxy_networks = network_roles(REVERSE_PROXY_APPLICATION_ID)
    shared = [role for role in network_roles(application_id) if role in proxy_networks]
    if not shared:
        raise ValueError(
            f"{application_id} shares no overlay with "
            f"{REVERSE_PROXY_APPLICATION_ID}, so no address carries its proxied requests"
        )
    return list(dict.fromkeys(subnets(shared)))
