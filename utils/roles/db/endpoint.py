"""HAProxy write endpoint of a central database engine in HA form."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from utils.roles.db.instances import engine_word, ha_spec

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

CHECK_TIMEOUT_DEFAULT = 1
CHECK_FALL_DEFAULT = 3
DOCKER_DNS = "127.0.0.11:53"
ADMIN_SOCKET = "/tmp/haproxy-admin.sock"  # noqa: S108 - socket inside the HAProxy container's private /tmp
CHECK_HTTP = "http"
CHECK_REDIS = "redis"
PRIVILEGED_PORT_LIMIT = 1024
KEEPALIVE_SYSCTLS = {
    "net.ipv4.tcp_keepalive_time": 300,
    "net.ipv4.tcp_keepalive_intvl": 30,
    "net.ipv4.tcp_keepalive_probes": 3,
}

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]+$")


class DbEndpointError(ValueError):
    pass


def endpoint_settings(application_id: str, ports: Mapping[str, int]) -> dict:
    """Resolve one engine's ``ha.endpoint`` against its ``ports.internal``.

    Args:
        application_id: HA-capable engine role, e.g. ``svc-db-openldap``.
        ports: the engine's merged ``ports.internal``, inventory overrides
            included, so HAProxy and the instances agree on every port.

    Returns:
        ``{"engine", "port", "backend_port", "check", "check_port",
        "check_path", "check_timeout", "check_fall"}``; ``backend_port``
        defaults to ``port``, the HTTP fields are None for a non-HTTP check,
        ``check_timeout`` (seconds) and ``check_fall`` (failed checks before a
        server is marked down) default to 1 and 3.
    """
    endpoint = ha_spec(application_id)["endpoint"]
    if not isinstance(endpoint, dict):
        raise DbEndpointError(
            f"db_endpoint: {application_id} declares no ha.endpoint in meta/services.yml"
        )

    def _port(field: str) -> int:
        key = endpoint.get(field)
        if key not in ports:
            raise DbEndpointError(
                f"db_endpoint: {application_id} ha.endpoint.{field} '{key}' "
                "names no ports.internal entry"
            )
        return int(ports[key])

    check = endpoint.get("check")
    http = check == CHECK_HTTP
    return {
        "engine": engine_word(application_id),
        "port": _port("port"),
        "backend_port": _port("backend_port" if "backend_port" in endpoint else "port"),
        "check": check,
        "check_port": _port("check_port") if http else None,
        "check_path": endpoint.get("check_path") if http else None,
        "check_timeout": int(endpoint.get("check_timeout", CHECK_TIMEOUT_DEFAULT)),
        "check_fall": int(endpoint.get("check_fall", CHECK_FALL_DEFAULT)),
    }


def unprivileged_port_start(port: int) -> int | None:
    """Return the ``net.ipv4.ip_unprivileged_port_start`` a non-root HAProxy
    needs to bind ``port``, or None when no sysctl is needed."""
    return port if port < PRIVILEGED_PORT_LIMIT else None


def endpoint_sysctls(port: int) -> dict[str, int]:
    """Return the sysctls of the HAProxy endpoint container.

    Keepalive probes every 300 s refresh Swarm's virtual-IP load balancer,
    which drops a connection idle for 900 s; a non-root HAProxy also needs
    ``net.ipv4.ip_unprivileged_port_start`` to bind a port below 1024.

    Args:
        port: client port the endpoint binds.
    """
    sysctls = dict(KEEPALIVE_SYSCTLS)
    start = unprivileged_port_start(port)
    if start is not None:
        sysctls["net.ipv4.ip_unprivileged_port_start"] = start
    return sysctls


def _server_line(
    service: str, backend_port: int, check_port: int | None, fall: int
) -> str:
    port = f" port {check_port}" if check_port else ""
    return (
        f"    server {service} {service}:{backend_port} check{port} "
        "resolvers docker resolve-prefer ipv4 init-addr none "
        f"inter 1s fastinter 500ms downinter 1s fall {fall} rise 1 "
        "on-marked-down shutdown-sessions"
    )


def render_haproxy_cfg(
    settings: dict,
    instances: Sequence[dict],
    *,
    check_user: str | None = None,
    check_password: str | None = None,
) -> str:
    """Return ``haproxy.cfg`` for one engine's write endpoint.

    Args:
        settings: ``endpoint_settings()`` of the engine.
        instances: ``build_instances()["instances"]`` of the HA form; each
            ``service`` is the instance's Swarm service name.
        check_user: ACL user the redis TCP check logs in as; required for a
            ``redis`` check.
        check_password: that user's password; required for a ``redis`` check.

    Returns:
        The configuration text, newline-terminated.
    """
    engine = settings["engine"]
    services = [i.get("service") for i in instances]
    if not services or not all(services):
        raise DbEndpointError(f"db_endpoint: {engine} needs at least one instance")

    check_port = settings["check_port"]
    if settings["check"] == CHECK_HTTP:
        if not check_port or not settings["check_path"]:
            raise DbEndpointError(
                f"db_endpoint: {engine} http check needs check_port and check_path"
            )
        check = [
            f"    option httpchk GET {settings['check_path']}",
            "    http-check expect status 200",
        ]
    elif settings["check"] == CHECK_REDIS:
        check_port = None
        for label, value in (
            ("check_user", check_user),
            ("check_password", check_password),
        ):
            if not value or not _SAFE_TOKEN.match(value):
                raise DbEndpointError(
                    f"db_endpoint: redis {label} must be a non-empty [A-Za-z0-9_-] token"
                )
        check = [
            "    option tcp-check",
            "    tcp-check connect",
            f"    tcp-check send AUTH\\ {check_user}\\ {check_password}\\r\\n",
            "    tcp-check expect string +OK",
            "    tcp-check send info\\ replication\\r\\n",
            "    tcp-check expect string role:master",
            "    tcp-check expect rstring connected_slaves:[1-9]",
            "    tcp-check send QUIT\\r\\n",
            "    tcp-check expect string +OK",
        ]
    else:
        raise DbEndpointError(
            f"db_endpoint: {engine} has unknown check '{settings['check']}' "
            f"(expected {CHECK_HTTP} or {CHECK_REDIS})"
        )

    lines = [
        "global",
        f"    stats socket {ADMIN_SOCKET} mode 600 level admin",
        "",
        "resolvers docker",
        f"    nameserver dns {DOCKER_DNS}",
        "    resolve_retries 3",
        "    timeout resolve 1s",
        "    timeout retry 1s",
        "    hold valid 1s",
        "    hold obsolete 1s",
        "",
        "defaults",
        "    mode tcp",
        "    option clitcpka",
        "    option srvtcpka",
        "    timeout connect 2s",
        "    timeout client 30m",
        "    timeout server 30m",
        "",
        f"frontend {engine}",
        f"    bind :{settings['port']}",
        f"    default_backend {engine}_writer",
        "",
        f"backend {engine}_writer",
        f"    timeout check {settings['check_timeout']}s",
        *check,
        *(
            _server_line(
                s, settings["backend_port"], check_port, settings["check_fall"]
            )
            for s in services
        ),
    ]
    return "\n".join(lines) + "\n"
