#
# Shared strict resolution helpers for Infinito.Nexus TLS/cert lookups.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError

from utils.domains.application_domain_index import resolve_app_id_for_domain

if TYPE_CHECKING:
    from collections.abc import Iterable

AVAILABLE_FLAVORS = {"letsencrypt", "self_signed"}


def as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def norm_domain(value: Any) -> str:
    return as_str(value).lower()


def require(variables: dict, name: str, expected_type: type | tuple[type, ...]) -> Any:
    if name not in variables:
        raise AnsibleError(f"tls_common: required variable '{name}' is missing")
    value = variables[name]
    if not isinstance(value, expected_type):
        raise AnsibleError(
            f"tls_common: variable '{name}' must be {expected_type}, got {type(value).__name__}"
        )
    return value


def get_path(data: Any, path: str, default: Any = None) -> Any:
    if not isinstance(data, dict):
        return default
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def want_get(data: Any, dotted: str) -> Any:
    if not dotted:
        return data
    cur: Any = data
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            raise AnsibleError(f"want='{dotted}' not found (missing '{part}')")
        cur = cur[part]
    return cur


def iter_domains(value: Any) -> Iterable[str]:
    """
    Flatten domains from the *global* domains mapping entry.
    Supports:
      - str
      - list[str]
      - dict[str, str]   (only one level, legacy behavior)
    """
    if isinstance(value, str):
        if value.strip():
            yield value.strip()
        return

    if isinstance(value, dict):
        for v in value.values():
            if isinstance(v, str) and v.strip():
                yield v.strip()
        return

    if isinstance(value, list):
        for v in value:
            if isinstance(v, str) and v.strip():
                yield v.strip()
        return


def uniq_preserve(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        s = as_str(it)
        if not s:
            continue
        s = norm_domain(s)
        if s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def resolve_app_id_from_domain(domains: dict, domain: str, *, err_prefix: str) -> str:
    """
    Legacy reverse-lookup from the *global* domains mapping.
    This does NOT know about per-app aliases/canonicals stored in applications.
    """
    needle = norm_domain(domain)
    matches: list[str] = []

    for app_id, val in domains.items():
        matches.extend(
            str(app_id) for d in iter_domains(val) if norm_domain(d) == needle
        )

    if not matches:
        raise AnsibleError(
            f"{err_prefix}: domain '{domain}' not found in domains mapping"
        )

    if len(matches) > 1:
        raise AnsibleError(
            f"{err_prefix}: domain '{domain}' is ambiguous, matches applications {matches}"
        )

    return matches[0]


def resolve_primary_domain_from_app(
    domains: dict, app_id: str, *, err_prefix: str
) -> str:
    if app_id not in domains:
        raise AnsibleError(
            f"{err_prefix}: application_id '{app_id}' not found in domains mapping"
        )

    val = domains[app_id]

    if isinstance(val, str):
        if not val:
            raise AnsibleError(f"{err_prefix}: domains['{app_id}'] is empty")
        return val

    if isinstance(val, dict):
        try:
            first_val = next(iter(val.values()))
        except StopIteration:
            raise AnsibleError(
                f"{err_prefix}: domains['{app_id}'] dict is empty"
            ) from None
        if not isinstance(first_val, str) or not first_val:
            raise AnsibleError(f"{err_prefix}: invalid primary domain for '{app_id}'")
        return first_val

    if isinstance(val, list):
        if not val:
            raise AnsibleError(f"{err_prefix}: domains['{app_id}'] list is empty")
        first = val[0]
        if not isinstance(first, str) or not first:
            raise AnsibleError(f"{err_prefix}: invalid primary domain for '{app_id}'")
        return first

    raise AnsibleError(
        f"{err_prefix}: domains['{app_id}'] has unsupported type {type(val).__name__}"
    )


def collect_domains_for_app(
    domains: dict, app_id: str, *, err_prefix: str
) -> list[str]:
    if app_id not in domains:
        raise AnsibleError(
            f"{err_prefix}: application_id '{app_id}' not found in domains mapping"
        )
    return uniq_preserve(list(iter_domains(domains[app_id])))


def collect_domains_global(domains: dict) -> list[str]:
    all_items: list[str] = []
    for val in domains.values():
        all_items.extend(list(iter_domains(val)))
    return uniq_preserve(all_items)


def resolve_term(
    term: str,
    *,
    domains: dict,
    applications: dict | None = None,
    forced_mode: str,
    err_prefix: str,
) -> tuple[str, str]:
    """
    Returns (app_id, primary_domain) where primary_domain is normalized lower-case.

    term can be:
      - application_id
      - domain (canonical or alias)

    forced_mode: "auto" | "domain" | "app"

    Behavior:
      1) If term is a domain and exists in *global* domains mapping -> primary_domain = that term (normalized).
      2) If term is a domain and only exists in applications[*].server.domains -> map to app_id,
         and primary_domain = canonical primary from global domains mapping (first entry).
    """
    t = as_str(term)
    if not t:
        raise AnsibleError(f"{err_prefix}: term is empty")

    forced = as_str(forced_mode).lower()
    if forced not in {"auto", "domain", "app"}:
        raise AnsibleError(f"{err_prefix}: mode must be one of: auto, domain, app")

    if forced == "domain":
        is_domain = True
    elif forced == "app":
        is_domain = False
    else:
        # keep your old heuristic
        is_domain = "." in t

    if is_domain:
        # 1) Try legacy reverse mapping (global domains mapping values).
        #    If this succeeds, the requested domain *is* a canonical/variant in the global mapping,
        #    so we keep it as primary.
        try:
            app_id_legacy = resolve_app_id_from_domain(
                domains, t, err_prefix=err_prefix
            )
            return str(app_id_legacy), norm_domain(t)
        except AnsibleError:
            pass

        # 2) Fallback: resolve via applications[*].server.domains.{canonical,aliases}
        apps = applications or {}
        if not isinstance(apps, dict):
            raise AnsibleError(
                f"{err_prefix}: applications must be dict when resolving domain terms"
            )

        app_id = resolve_app_id_for_domain(apps, t)
        if not app_id and t.lower().startswith("www."):
            bare = t[4:]
            try:
                app_id_legacy = resolve_app_id_from_domain(
                    domains, bare, err_prefix=err_prefix
                )
                return str(app_id_legacy), norm_domain(bare)
            except AnsibleError:
                pass
            app_id = resolve_app_id_for_domain(apps, bare)
        if not app_id:
            raise AnsibleError(
                f"{err_prefix}: domain '{t}' not found (domains/applications)"
            )

        # For alias terms, primary should be the canonical primary from global domains mapping
        primary = norm_domain(
            resolve_primary_domain_from_app(domains, str(app_id), err_prefix=err_prefix)
        )
        return str(app_id), primary

    # app-id path
    app_id = t
    primary = norm_domain(
        resolve_primary_domain_from_app(domains, app_id, err_prefix=err_prefix)
    )
    return app_id, primary


def resolve_enabled(app: dict, enabled_default: bool) -> bool:
    override = get_path(app, "server.tls.enabled", None)
    return enabled_default if override is None else bool(override)


def resolve_mode(
    app: dict, enabled: bool, mode_default: str, *, err_prefix: str
) -> str:
    if not enabled:
        return "off"
    override = get_path(app, "server.tls.flavor", None)
    if isinstance(override, str) and override.strip():
        mode = override.strip()
    else:
        mode = mode_default

    if mode not in AVAILABLE_FLAVORS:
        raise AnsibleError(
            f"{err_prefix}: TLS_MODE/server.tls.flavor must be one of {sorted(AVAILABLE_FLAVORS)}, got '{mode}'"
        )
    return mode


def resolve_le_name(app: dict, domain: str) -> str:
    override = get_path(app, "server.tls.letsencrypt_cert_name", "")
    name = as_str(override)
    return name or domain


def override_san_list(app: dict) -> list[str] | None:
    raw = get_path(app, "server.tls.domains_san", None)
    if raw is None:
        return None
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []
