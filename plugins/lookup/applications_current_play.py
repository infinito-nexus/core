from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from utils.cache.yaml import load_yaml_any
from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.applications.in_group_deps import applications_if_group_and_all_deps
from utils.cache.applications import get_merged_applications
from utils.cache.base import (
    _cache_key,
    _resolve_roles_dir,
    _stable_variables_signature,
)
from utils.service_registry import build_service_registry_from_applications


_CURRENT_PLAY_CACHE: "dict[tuple, Dict[str, Any]]" = {}


def _reset_cache_for_tests() -> None:
    _CURRENT_PLAY_CACHE.clear()


class LookupModule(LookupBase):
    """
    Return the current play application mapping using the shared resolver from
    utils/applications/in_group_deps.
    """

    def run(
        self,
        terms: List[Any],
        variables: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        roles_dir_arg = kwargs.get("roles_dir")
        project_root = self._get_project_root()
        roles_dir = roles_dir_arg or os.path.join(project_root, "roles")

        group_names = vars_.get("group_names", []) or []
        resolved_roles_dir = _resolve_roles_dir(roles_dir=roles_dir_arg)
        cache_key = (
            _cache_key(resolved_roles_dir),
            _stable_variables_signature(vars_),
            tuple(group_names),
        )
        cached = _CURRENT_PLAY_CACHE.get(cache_key)
        if cached is not None:
            return [cached]

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=roles_dir_arg,
            templar=getattr(self, "_templar", None),
        )
        service_registry = build_service_registry_from_applications(applications)

        try:
            result = applications_if_group_and_all_deps(
                applications,
                group_names,
                project_root=project_root,
                roles_dir=roles_dir,
                service_registry=service_registry,
                meta_deps_resolver=self._meta_deps,
            )
        except ValueError as exc:
            raise AnsibleError(f"applications_current_play: {exc}") from exc

        _CURRENT_PLAY_CACHE[cache_key] = result
        return [result]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_project_root(self) -> str:
        plugin_dir = os.path.dirname(__file__)
        return os.path.abspath(os.path.join(plugin_dir, "..", ".."))

    def _meta_deps(self, role: str, roles_dir: str) -> List[str]:
        meta_file = os.path.join(roles_dir, role, "meta", "main.yml")
        if not os.path.isfile(meta_file):
            return []
        try:
            meta = load_yaml_any(meta_file, default_if_missing={}) or {}
        except Exception:
            return []
        if not isinstance(meta, dict):
            return []
        deps = []
        for dep in meta.get("dependencies", []):
            if isinstance(dep, str):
                deps.append(dep)
            elif isinstance(dep, dict):
                name = dep.get("role") or dep.get("name")
                if name:
                    deps.append(name)
        return deps
