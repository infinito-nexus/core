from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml
from utils.roles.applications.services.errors import ServicesResolutionError
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    is_explicit_truth,
    resolve_service_dependency_roles_from_config,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

_ROLES_ROOT = PROJECT_ROOT / "roles"


def _stable_dedup(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _as_mapping(obj: object) -> dict:
    return obj if isinstance(obj, dict) else {}


def _is_enabled_shared(svc: object) -> bool:
    svc = _as_mapping(svc)
    return is_explicit_truth(svc.get("enabled")) and is_explicit_truth(
        svc.get("shared")
    )


def _load_service_registry(roles_root: Path = _ROLES_ROOT) -> dict[str, Any]:
    try:
        return build_service_registry_from_roles_dir(roles_root)
    except Exception as exc:
        raise ServicesResolutionError(
            f"Failed to discover services from role configs in {roles_root}: {exc}"
        ) from exc


def resolve_direct_service_roles_from_config(
    config: dict,
    service_registry: dict[str, Any] | None = None,
) -> list[str]:
    """
    Single source of truth for "service -> provider role(s)" mapping.
    """
    if service_registry is None:
        service_registry = _load_service_registry()
    try:
        return _stable_dedup(
            resolve_service_dependency_roles_from_config(
                _as_mapping(config),
                service_registry,
            )
        )
    except Exception as exc:
        raise ServicesResolutionError(str(exc)) from exc


class ServicesResolver:
    """
    Resolve shared-provider roles transitively from role meta/services.yml.

    Note:
    - Transitively follows provider roles by reading THEIR configs and applying the same
      resolve_direct_service_roles_from_config() logic.
    """

    def __init__(
        self,
        roles_root: Path,
        services_file: Path | None = None,
    ) -> None:
        self.roles_root = roles_root
        self._service_registry = _load_service_registry(
            services_file or self.roles_root
        )

    def _role_dir(self, role_name: str) -> Path:
        return self.roles_root / role_name

    def _role_services_path(self, role_name: str) -> Path:
        # The services manifest lives at meta/services.yml. The file
        # root IS the services map (no `compose.services` wrapper).
        return self._role_dir(role_name) / ROLE_FILE_META_SERVICES

    def _load_role_config(self, role_name: str) -> dict:
        services_path = self._role_services_path(role_name)
        if not services_path.exists():
            return {}
        try:
            services = load_yaml(services_path) or {}
        except Exception as exc:
            raise ServicesResolutionError(
                f"Failed to parse {services_path}: {exc}"
            ) from exc
        return {"services": services} if isinstance(services, dict) else {}

    def _validate_role_exists(self, role_name: str) -> None:
        role_dir = self._role_dir(role_name)
        if not role_dir.is_dir():
            raise ServicesResolutionError(
                f"Resolved service role {role_name!r} does not exist "
                f"(missing folder {role_dir})"
            )

    def direct_includes_from_config(self, config: dict) -> list[str]:
        return resolve_direct_service_roles_from_config(config, self._service_registry)

    def resolve_transitively(self, root_role_name: str) -> list[str]:
        """
        BFS over roles discovered via service flags.
        Queue order is stable, results are deduped.
        """
        resolved: list[str] = []
        seen: set[str] = set()

        root_cfg = self._load_role_config(root_role_name)
        queue: list[str] = self.direct_includes_from_config(root_cfg)

        while queue:
            role_name = queue.pop(0)
            if role_name in seen:
                continue

            self._validate_role_exists(role_name)

            seen.add(role_name)
            resolved.append(role_name)

            cfg = self._load_role_config(role_name)
            queue.extend(
                inc for inc in self.direct_includes_from_config(cfg) if inc not in seen
            )

        return resolved
