import sys
from collections.abc import Mapping
from pathlib import Path

from ansible.errors import AnsibleError

from utils.networks.reachability import CLEARNET, network, network_of, sibling_domain
from utils.roles.applications.config import get
from utils.roles.applications.status_codes import DEFAULT_OK, codes_by_key
from utils.tls_common import resolve_enabled, resolve_term

# nocheck: project-root-import
_BASE_DIR = str(Path(__file__).resolve().parents[3])
_MODULE_UTILS_DIR = str(Path(_BASE_DIR) / "utils")
for _p in (_BASE_DIR, _MODULE_UTILS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _to_list(x, *, allow_mapping: bool = True):
    """Normalize into a flat list of **strings only**."""
    if x is None:
        return []

    if isinstance(x, bytes):
        return [x.decode("utf-8", errors="replace")]
    if isinstance(x, str):
        return [x]

    if isinstance(x, (list, tuple, set)):
        out = []
        for v in x:
            if isinstance(v, (list, tuple, set)):
                out.extend(_to_list(v, allow_mapping=False))
            elif isinstance(v, bytes):
                out.append(v.decode("utf-8", errors="replace"))
            elif isinstance(v, str):
                out.append(v)
            elif isinstance(v, Mapping):
                continue
        return out

    if isinstance(x, Mapping) and allow_mapping:
        out = []
        for v in x.values():
            out.extend(_to_list(v, allow_mapping=True))
        return out

    return []


def _extract_redirect_sources(redirect_maps):
    """Extract a set of source domains from redirect maps."""
    sources = set()
    if not redirect_maps:
        return sources

    def _add_one(obj):
        if isinstance(obj, str) and obj:
            sources.add(obj)
        elif isinstance(obj, Mapping):
            s = obj.get("source")
            if isinstance(s, str) and s:
                sources.add(s)

    if isinstance(redirect_maps, (list, tuple, set)):
        for item in redirect_maps:
            _add_one(item)
    else:
        _add_one(redirect_maps)

    return sources


def _normalize_selection(group_names):
    """Return a non-empty set of group names, or raise ValueError."""
    if isinstance(group_names, (list, set, tuple)):
        sel = {str(x) for x in group_names if str(x)}
    elif isinstance(group_names, str):
        sel = {g.strip() for g in group_names.split(",") if g.strip()}
    else:
        sel = set()

    if not sel:
        raise ValueError(
            "web_health_expectations: 'group_names' must be provided and non-empty"
        )
    return sel


def _apply_served_view(per_app, served_domains, primary_domain, node_onion):
    """Rewrite each app's canonical expectations to the domains the node serves.

    Args:
        per_app: expected codes per canonical domain, per application.
        served_domains: ``lookup('domains')`` of this host.
        primary_domain: the node's ``DOMAIN_PRIMARY``.
        node_onion: the node onion address, empty without Tor.

    A served domain inherits the codes of its clearnet sibling; an app the
    map does not list keeps its declared domains.
    """
    if not isinstance(served_domains, Mapping):
        return
    primary = str(primary_domain or "").strip()
    node = str(node_onion or "").strip()
    for app_id, exp in per_app.items():
        served = _to_list(served_domains.get(app_id), allow_mapping=True)
        if not served:
            continue
        view = {}
        for domain in served:
            source = (
                domain
                if domain in exp
                else sibling_domain(domain, CLEARNET, primary, node)
            )
            if source in exp:
                view[domain] = exp[source]
        per_app[app_id] = view


def web_health_expectations(
    applications,
    www_enabled: bool = False,
    group_names=None,
    redirect_maps=None,
    primary_domain=None,
    node_onion=None,
    served_domains=None,
):
    """Produce a **flat mapping**: domain -> [expected_status_codes].

    Selection (REQUIRED):
      - `group_names` must be provided and non-empty.
      - Only include applications whose key is in `group_names`.

    Rules:
      - Canonical domains (dict-key overrides, else default, else DEFAULT_OK).
      - Flat canonical (default, else DEFAULT_OK).
      - Aliases always [301].
      - No legacy fallbacks (ignore 'home'/'landingpage').
      - `redirect_maps`: force <source> -> [301] and override app-derived entries.
      - If `www_enabled`: add and/or force www.* -> [301] for all domains.
      - Served view: with `served_domains` (the host's `lookup('domains')`)
        every app's canonical domains become the ones the node serves, each
        inheriting the codes of its clearnet sibling via `node_onion`.
    """
    if not isinstance(applications, Mapping):
        return {}

    selection = _normalize_selection(group_names)

    per_app = {}
    per_alias = {}

    for app_id in applications:
        if app_id not in selection:
            continue

        canonical_raw = get(
            applications, app_id, "domains.canonical", strict=False, default=[]
        )
        aliases_raw = get(
            applications, app_id, "domains.aliases", strict=False, default=[]
        )
        aliases = _to_list(aliases_raw, allow_mapping=True)

        sc_map = codes_by_key(
            get(applications, app_id, "server.status_codes", strict=False, default={})
        )

        suppressed = set()
        services_raw = get(applications, app_id, "services", strict=False, default={})
        if isinstance(services_raw, Mapping):
            for svc in services_raw.values():
                if not isinstance(svc, Mapping) or "domains" not in svc:
                    continue
                if svc.get("enabled"):
                    continue
                for key in _to_list(svc.get("domains"), allow_mapping=False):
                    if key:
                        suppressed.add(str(key))

        app_exp = {}
        if isinstance(canonical_raw, Mapping) and canonical_raw:
            for key, domains in canonical_raw.items():
                if str(key) in suppressed:
                    continue
                domains_list = _to_list(domains, allow_mapping=False)
                codes = sc_map.get(key) or sc_map.get("default")
                expected = list(codes) if codes else list(DEFAULT_OK)
                for d in domains_list:
                    if d:
                        app_exp[d] = expected
        else:
            for d in _to_list(canonical_raw, allow_mapping=True):
                if not d:
                    continue
                codes = sc_map.get("default")
                app_exp[d] = list(codes) if codes else list(DEFAULT_OK)

        per_app[app_id] = app_exp
        per_alias[app_id] = {d: [301] for d in aliases if d}

    primary = str(primary_domain or "").strip()
    if primary and "web-opt-rdr-domains" not in selection:
        for app_exp in per_app.values():
            app_exp.pop(primary, None)

    _apply_served_view(per_app, served_domains, primary_domain, node_onion)

    expectations = {}
    for app_id, app_exp in per_app.items():
        expectations.update(app_exp)
        expectations.update(per_alias[app_id])

    for src in _extract_redirect_sources(redirect_maps):
        expectations[src] = [301]

    if www_enabled:
        add = {}
        for d in expectations:
            if d.startswith("www."):
                continue
            if network_of(d) != CLEARNET:
                continue
            add[f"www.{d}"] = [301]
        expectations.update(add)
        for d in list(expectations.keys()):
            if d.startswith("www."):
                expectations[d] = [301]

    return {k: expectations[k] for k in sorted(expectations.keys())}


def web_health_targets(expectations, applications, served_domains, tls_enabled):
    """Attach the probe scheme and timeout to every expected domain.

    Args:
        expectations: output of ``web_health_expectations``.
        applications: merged applications tree.
        served_domains: ``lookup('domains')`` of this host.
        tls_enabled: ``TLS_ENABLED``.

    Returns:
        ``{domain: {"codes": [...], "scheme": "http"|"https", "timeout": s}}``;
        the scheme follows the same per-domain resolution as ``lookup('tls')``
        and the timeout comes from the domain's network.
    """
    targets = {}
    for domain, codes in (expectations or {}).items():
        try:
            app_id, resolved = resolve_term(
                domain,
                domains=served_domains or {},
                applications=applications or {},
                forced_mode="domain",
                err_prefix="web_health_targets",
            )
            app = (applications or {}).get(app_id) or {}
        except AnsibleError:
            resolved, app = domain, {}
        enabled = resolve_enabled(app, bool(tls_enabled), primary_domain=resolved)
        targets[domain] = {
            "codes": list(codes),
            "scheme": "https" if enabled else "http",
            "timeout": network(network_of(domain)).probe_timeout,
        }
    return targets


class FilterModule:
    def filters(self):
        return {
            "web_health_expectations": web_health_expectations,
            "web_health_targets": web_health_targets,
        }
