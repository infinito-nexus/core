#
# Shared helpers for indexing application domains from
# applications[app_id].domains.{canonical,aliases}.
#
# Supports canonical/aliases being:
# - str
# - list
# - dict (possibly nested, like "web/api/view" variants)
#
# Note:
# This module does NOT template Jinja. It expects values to already
# be rendered at lookup runtime.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ansible.errors import AnsibleError

if TYPE_CHECKING:
    from collections.abc import Iterable


def _norm_domain(value: Any) -> str:
    s = str(value).strip() if value is not None else ""
    return s.lower()


def _flatten_str_values(value: Any) -> list[str]:
    """
    Recursively flatten strings from value.
    Accepts str | list | dict | nested combinations.
    Returns list[str] preserving discovery order (best effort).
    """
    out: list[str] = []

    def walk(v: Any) -> None:
        if v is None:
            return
        if isinstance(v, str):
            s = v.strip()
            if s:
                out.append(s)
            return
        if isinstance(v, list):
            for item in v:
                walk(item)
            return
        if isinstance(v, dict):
            for vv in v.values():
                walk(vv)
            return

    walk(value)
    return out


def iter_app_domains(app_conf: Any, include_aliases: bool = True) -> Iterable[str]:
    """
    Yield all canonical + alias domains from an app config.

    Expected structure:
      applications[app_id].domains.canonical
      applications[app_id].domains.aliases
    """
    if not isinstance(app_conf, dict):
        return []

    domains = app_conf.get("domains", {})
    if not isinstance(domains, dict):
        return []

    canonical = domains.get("canonical", [])
    result: list[str] = []
    result.extend(_flatten_str_values(canonical))
    if include_aliases:
        aliases = domains.get("aliases", [])
        result.extend(_flatten_str_values(aliases))
    return result


def build_domain_index(
    applications: dict[str, Any], include_aliases: bool = True
) -> dict[str, str]:
    """
    Build a case-insensitive domain -> application_id index.
    If the same domain appears in multiple apps (case-insensitive), raises an error.
    """
    if not isinstance(applications, dict):
        raise AnsibleError("application_domain_index: applications must be a dict")

    index: dict[str, str] = {}
    collisions: dict[str, set[str]] = {}

    for app_id, app_conf in applications.items():
        for d in iter_app_domains(app_conf, include_aliases=include_aliases):
            nd = _norm_domain(d)
            if not nd:
                continue

            if nd in index and index[nd] != app_id:
                collisions.setdefault(nd, set()).update({index[nd], app_id})
            else:
                index[nd] = app_id

    if collisions:
        parts = []
        for domain, apps in sorted(collisions.items(), key=lambda x: x[0]):
            parts.append(f"{domain}: {sorted(apps)}")
        raise AnsibleError(
            "application_domain_index: domain collision across applications (ambiguous mapping): "
            + "; ".join(parts)
        )

    return index


def resolve_app_id_for_domain(
    applications: dict[str, Any],
    domain: str,
) -> str | None:
    """
    Resolve application_id for a given domain (canonical or alias) by scanning
    applications[*].domains.

    Returns None if not found.
    """
    nd = _norm_domain(domain)
    if not nd:
        return None

    idx = build_domain_index(applications)
    return idx.get(nd)
