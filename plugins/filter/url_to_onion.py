from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit


def to_onion_url(url: str, tor_node: str, primary_domain: str) -> str:
    """Rewrite a browser-facing clearnet URL to its ``.onion`` mirror.

    When ``tor_node`` is set (svc-net-tor deployed) and the URL's host is the
    ``primary_domain`` or a subdomain of it, swap that suffix for ``tor_node``
    and force the ``http`` scheme (onion services are plaintext-only). Anything
    else — empty inputs, a host not under ``primary_domain``, an unparseable
    value — is returned unchanged, so the filter is a safe no-op on clearnet.
    """
    if not url or not tor_node or not primary_domain:
        return url

    parts = urlsplit(url if "://" in url else "//" + url)
    host = parts.hostname or ""
    suffix = "." + primary_domain

    if host == primary_domain:
        onion_host = tor_node
    elif host.endswith(suffix):
        onion_host = host[: -len(primary_domain)] + tor_node
    else:
        return url

    return urlunsplit(("http", onion_host, parts.path, parts.query, parts.fragment))


class FilterModule:
    def filters(self):
        return {"to_onion_url": to_onion_url}
