from __future__ import annotations

import http.client
import ssl


def tls_context(cafile: str | None) -> ssl.SSLContext:
    """
    Args:
        cafile: the deployment CA under ``TLS_MODE`` ``self_signed``, trusted
            beside the system store; None trusts the system store alone.
    """
    context = ssl.create_default_context()
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if cafile:
        context.load_verify_locations(cafile=cafile)
    return context


def https_connection(
    host: str,
    port: int,
    context: ssl.SSLContext,
    timeout: float,
    proxy: str | None = None,
) -> http.client.HTTPSConnection:
    """
    Args:
        host: the HTTPS server.
        port: its port.
        context: see ``tls_context``.
        timeout: the socket timeout in seconds.
        proxy: ``<name>:<port>`` of an egress proxy (``EGRESS_PROXY``); None
            connects to the server directly.

    Returns:
        A connection to the server, through a ``CONNECT`` tunnel of the proxy
        when one is given, whose certificate is checked against ``host``.
    """
    if not proxy:
        return http.client.HTTPSConnection(host, port, context=context, timeout=timeout)
    name, _, proxy_port = proxy.rpartition(":")
    connection = http.client.HTTPSConnection(
        name, int(proxy_port), context=context, timeout=timeout
    )
    connection.set_tunnel(host, port)
    return connection
