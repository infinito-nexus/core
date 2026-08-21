"""
Jinja filter: `external_asset_origins` extracts the third-party asset hosts an
application (or every application) declares in `csp.whitelist.*`.

The result feeds the web-svc-mirror privacy proxy: the mirror's nginx vhost
whitelists exactly these hosts as proxy upstreams, and the body-filter rewrite
maps `https://<host>/...` to `<mirror>/<host>/...` in served HTML.

Only literal `https://<host>` tokens count as external assets:
  - tokens containing unresolved Jinja (`{{ ... }}`) point at deployment-own
    domains and are skipped,
  - wildcard tokens (`*`) cannot be mirrored deterministically,
  - hosts on the deployment's primary domain (or `.onion`) are already local.
"""

from urllib.parse import urlsplit


def _iter_whitelist_tokens(app_config):
    whitelist = ((app_config or {}).get("csp") or {}).get("whitelist", {}) or {}
    for raw_tokens in whitelist.values():
        tokens = [raw_tokens] if isinstance(raw_tokens, str) else raw_tokens
        if not isinstance(tokens, (list, tuple)):
            continue
        for token in tokens:
            if isinstance(token, str):
                yield token.strip()


def _external_host(token, primary_domain):
    if not token.startswith("https://"):
        return None
    if "{{" in token or "*" in token:
        return None
    host = urlsplit(token).hostname or ""
    if not host or "." not in host:
        return None
    if host.endswith(".onion"):
        return None
    if primary_domain and (
        host == primary_domain or host.endswith("." + primary_domain)
    ):
        return None
    return host.lower()


def external_asset_origins(applications, application_id=None, primary_domain=""):
    """
    Return the sorted list of external asset hosts.

    application_id: restrict to one application; None aggregates across all.
    primary_domain: the deployment's primary domain (its hosts are not external).
    """
    if not isinstance(applications, dict):
        return []
    if application_id is not None:
        selected = {application_id: applications.get(application_id) or {}}
    else:
        selected = applications
    hosts = set()
    for app_config in selected.values():
        for token in _iter_whitelist_tokens(app_config):
            host = _external_host(token, primary_domain)
            if host:
                hosts.add(host)
    return sorted(hosts)


class FilterModule:
    def filters(self):
        return {
            "external_asset_origins": external_asset_origins,
        }
