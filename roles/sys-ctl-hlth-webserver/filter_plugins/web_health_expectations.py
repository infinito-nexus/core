import sys
from collections.abc import Mapping
from pathlib import Path

from utils.roles.applications.config import get  # reuse existing helper

# Allow imports from utils (same trick as your config filter).
# Role-bundled plugin: Ansible loads by file path with no package
# context, so `from . import PROJECT_ROOT` cannot resolve here.
# nocheck: project-root-import
_BASE_DIR = str(Path(__file__).resolve().parents[3])
_MODULE_UTILS_DIR = str(Path(_BASE_DIR) / "utils")
for _p in (_BASE_DIR, _MODULE_UTILS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

DEFAULT_OK = [200, 302, 301]


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


def _valid_http_code(x):
    """Return int(x) if 100 <= code <= 599 else None."""
    try:
        v = int(x)
    except (TypeError, ValueError):
        return None
    return v if 100 <= v <= 599 else None


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


def _normalize_codes(x):
    """
    Accepts:
      - single code (int or str)
      - list/tuple/set of codes
    Returns a de-duplicated list of valid ints (100..599) in original order.
    """
    if x is None:
        return []
    if isinstance(x, (list, tuple, set)):
        out = []
        seen = set()
        for v in x:
            c = _valid_http_code(v)
            if c is not None and c not in seen:
                seen.add(c)
                out.append(c)
        return out
    c = _valid_http_code(x)
    return [c] if c is not None else []


def _apply_onion_deploy_view(per_app, applications, primary_domain, node_onion):
    """Rewrite each app's expectation domains to what the current deploy serves:
    for a ``services.tor.enabled`` app the onion domains replace (``exclusive``)
    or accompany (dual) the clearnet ones, reusing ``_inject_onion_domains`` and
    letting each onion domain inherit its clearnet source's status codes."""
    node = str(node_onion or "").strip()
    primary = str(primary_domain or "").strip()
    if not node or not primary:
        return

    from utils.cache.domains import _inject_onion_domains, _onion_of

    clearnet_lists = {app: list(exp.keys()) for app, exp in per_app.items()}
    served = _inject_onion_domains(clearnet_lists, applications, primary, node)

    for app_id, exp in per_app.items():
        onion_codes = {}
        for d, codes in exp.items():
            o = _onion_of(str(d), primary, node)
            if o:
                onion_codes[o] = codes
        served_list = served.get(app_id, list(exp.keys()))
        per_app[app_id] = {
            s: (exp[s] if s in exp else onion_codes[s])
            for s in served_list
            if s in exp or s in onion_codes
        }


def web_health_expectations(
    applications,
    www_enabled: bool = False,
    group_names=None,
    redirect_maps=None,
    primary_domain=None,
    node_onion=None,
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
      - Deploy-aware onion view: when `primary_domain` and `node_onion` are set
        (svc-net-tor deployed), each `services.tor.enabled` app's clearnet
        domains are swapped (exclusive) or extended (dual) with their onion
        domains, so the probe checks exactly what the current deploy serves.
    """
    if not isinstance(applications, Mapping):
        return {}

    selection = _normalize_selection(group_names)

    per_app = {}

    for app_id in applications:
        if app_id not in selection:
            continue

        canonical_raw = get(
            applications, app_id, "server.domains.canonical", strict=False, default=[]
        )
        aliases_raw = get(
            applications, app_id, "server.domains.aliases", strict=False, default=[]
        )
        aliases = _to_list(aliases_raw, allow_mapping=True)

        sc_raw = get(
            applications, app_id, "server.status_codes", strict=False, default={}
        )
        sc_map = {}
        if isinstance(sc_raw, Mapping):
            for k, v in sc_raw.items():
                codes = _normalize_codes(v)
                if codes:
                    sc_map[str(k)] = codes

        app_exp = {}
        if isinstance(canonical_raw, Mapping) and canonical_raw:
            for key, domains in canonical_raw.items():
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

        for d in aliases:
            if d:
                app_exp[d] = [301]

        per_app[app_id] = app_exp

    _apply_onion_deploy_view(per_app, applications, primary_domain, node_onion)

    expectations = {}
    for app_exp in per_app.values():
        expectations.update(app_exp)

    for src in _extract_redirect_sources(redirect_maps):
        expectations[src] = [301]

    if www_enabled:
        node = str(node_onion or "").strip()
        add = {}
        for d in expectations:
            if d.startswith("www."):
                continue
            if node and d.endswith(node):
                continue
            add[f"www.{d}"] = [301]
        expectations.update(add)
        for d in list(expectations.keys()):
            if d.startswith("www."):
                expectations[d] = [301]

    return {k: expectations[k] for k in sorted(expectations.keys())}


class FilterModule:
    def filters(self):
        return {
            "web_health_expectations": web_health_expectations,
        }
