from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.applications.config import get
from utils.cache.applications import get_merged_applications
from utils.service_registry import (
    build_role_to_primary_service_key,
    build_service_registry_from_applications,
    canonical_service_key,
    equivalent_service_keys,
)


def _get_service_flag(
    applications: Dict[str, Any],
    app_id: str,
    service_keys: List[str],
    flag: str,
) -> bool:
    return any(
        bool(
            get(
                applications=applications,
                application_id=app_id,
                config_path=f"services.{service_key}.{flag}",
                strict=False,
                default=False,
                skip_missing_app=True,
            )
        )
        for service_key in service_keys
    )


def _get_enabled_service_keys(
    applications: Dict[str, Any],
    app_id: str,
) -> List[str]:
    services = get(
        applications=applications,
        application_id=app_id,
        config_path="services",
        strict=False,
        default={},
        skip_missing_app=True,
    )
    if not isinstance(services, dict):
        return []
    return [
        k
        for k, v in services.items()
        if isinstance(v, dict) and v.get("enabled", False)
    ]


def _resolve_service_provider_app_id(
    applications: Dict[str, Any],
    service_registry: Dict[str, Any],
    service_key: str,
) -> Optional[str]:
    entry = service_registry.get(service_key)
    if not isinstance(entry, dict):
        return None

    role = entry.get("role")
    if isinstance(role, str) and role:
        return role
    return None


def _is_service_required(
    applications: Dict[str, Any],
    service_registry: Dict[str, Any],
    app_id: str,
    service_key: str,
    visited: Set[str],
) -> bool:
    """
    Return True if app_id directly or transitively (via its enabled services)
    has service_key with both enabled: true AND shared: true.
    Uses visited to prevent infinite loops.

    Exposed via the ``required`` flag on the ``service`` lookup result.
    """
    if app_id in visited:
        return False
    visited.add(app_id)

    service_keys = equivalent_service_keys(service_registry, service_key)
    enabled = _get_service_flag(applications, app_id, service_keys, "enabled")
    shared = _get_service_flag(applications, app_id, service_keys, "shared")
    if enabled and shared:
        return True

    for svc in _get_enabled_service_keys(applications, app_id):
        if svc == service_key:
            continue
        dep_app_id = _resolve_service_provider_app_id(
            applications, service_registry, svc
        )
        if dep_app_id and dep_app_id in applications:
            if _is_service_required(
                applications, service_registry, dep_app_id, service_key, visited
            ):
                return True

    return False


def _build_role_to_key(service_registry: Dict[str, Any]) -> Dict[str, str]:
    return build_role_to_primary_service_key(service_registry)


def _resolve_term(
    term: str,
    service_registry: Dict[str, Any],
    role_to_key: Dict[str, str],
) -> Tuple[str, str]:
    """
    Resolve a term (service key or role name) to (service_key, role).
    Raises AnsibleError if the term is not a known key or role.
    """
    if term in service_registry:
        entry = service_registry[term]
        role = entry.get("role", "")
        return term, str(role)
    if term in role_to_key:
        key = role_to_key[term]
        entry = service_registry[key]
        role = entry.get("role", "")
        return key, str(role)
    raise AnsibleError(
        f"service: '{term}' is neither a known service key nor a known role name. "
        f"Known keys: {sorted(service_registry)}. "
        f"Known roles: {sorted(role_to_key)}."
    )


def _compute_flags(
    applications: Dict[str, Any],
    group_names: List[str],
    service_registry: Dict[str, Any],
    service_key: str,
) -> Dict[str, bool]:
    deployed = [app_id for app_id in group_names if app_id in applications]
    equivalent_keys = equivalent_service_keys(service_registry, service_key)
    any_enabled = any(
        _get_service_flag(applications, app_id, equivalent_keys, "enabled")
        for app_id in deployed
    )
    any_shared = any(
        _get_service_flag(applications, app_id, equivalent_keys, "shared")
        for app_id in deployed
    )
    primary_key = canonical_service_key(service_registry, service_key)
    any_required = any(
        _is_service_required(applications, service_registry, app_id, primary_key, set())
        for app_id in deployed
    )
    return {"enabled": any_enabled, "shared": any_shared, "required": any_required}


class LookupModule(LookupBase):
    """
    Resolve a service by key or role name and return its aggregated deployment flags.

    Usage:
      lookup('service', 'matomo')
      lookup('service', 'web-app-matomo')   # resolved via reverse mapping

    Reads 'applications' and 'group_names' from Ansible variables and discovers
    service providers from the role-local services metadata.

    Returns a dict per term:
      id      — canonical service key  (e.g. 'matomo')
      role    — provider role name     (e.g. 'web-app-matomo')
      enabled — True if any deployed app has services.<key>.enabled: true
      shared  — True if any deployed app has services.<key>.shared: true
      required — True if any deployed app has both enabled AND shared (direct
                 or transitively via its own enabled service dependencies).
                 "Required" was chosen over "needed" to express that the
                 service is contractually required by a real consumer, not
                 merely convenient.
    """

    def run(
        self,
        terms: List[Any],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        if not terms:
            return []

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        group_names = vars_.get("group_names", [])
        if not isinstance(group_names, list):
            raise AnsibleError(
                "service: required variable 'group_names' must be a list"
            )

        service_registry = build_service_registry_from_applications(applications)

        role_to_key = _build_role_to_key(service_registry)

        results: List[Dict[str, Any]] = []
        for term in terms:
            term_str = str(term).strip()
            if not term_str:
                raise AnsibleError("service: service key/role must not be empty")

            service_key, role = _resolve_term(term_str, service_registry, role_to_key)
            flags = _compute_flags(
                applications, group_names, service_registry, service_key
            )
            results.append({"id": service_key, "role": role, **flags})

        return results
