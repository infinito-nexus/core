from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from plugins.lookup import PROJECT_ROOT

# nocheck: lookup-cache-import (derives the current-play applications view)
from utils.cache.applications import get_merged_applications
from utils.cache.base import (
    _cache_key,
    _resolve_roles_dir,
    _stable_variables_signature,
)
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.in_group_deps import applications_if_group_and_all_deps
from utils.roles.applications.services.registry import (
    build_service_registry_from_applications,
)
from utils.roles.mapping import ROLE_FILE_META_MAIN

_CURRENT_PLAY_CACHE: dict[tuple, dict[str, Any]] = {}


def _reset_cache_for_tests() -> None:
    _CURRENT_PLAY_CACHE.clear()


class LookupModule(LookupBase):
    """
    Return the current play application mapping using the shared resolver from
    utils/roles/applications/in_group_deps.
    """

    def run(
        self,
        terms: list[Any],
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        roles_dir_arg = kwargs.get("roles_dir")
        project_root = self._get_project_root()
        roles_dir = roles_dir_arg or str(Path(project_root) / "roles")

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
        except (TypeError, ValueError) as exc:
            raise AnsibleError(f"applications_current_play: {exc}") from exc

        _CURRENT_PLAY_CACHE[cache_key] = result
        return [result]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_project_root(self) -> str:
        return str(PROJECT_ROOT)

    def _meta_deps(self, role: str, roles_dir: str) -> list[str]:
        meta_file = str(Path(roles_dir) / role / ROLE_FILE_META_MAIN)
        if not Path(meta_file).is_file():
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
