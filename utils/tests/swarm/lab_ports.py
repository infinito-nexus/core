from __future__ import annotations

from typing import TYPE_CHECKING, Any

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.mapping import ROLE_FILE_META_SERVICES

if TYPE_CHECKING:
    from collections.abc import Iterable

LAB_RESOLVER_PORT = 53
LAB_REMAPPED_PORT = 1053


def _public_ports(service: Any) -> dict[str, Any]:
    if not isinstance(service, dict):
        return {}
    ports = service.get("ports")
    if not isinstance(ports, dict):
        return {}
    public = ports.get("public")
    return public if isinstance(public, dict) else {}


def lab_port_overrides(include: Iterable[str]) -> dict[str, Any]:
    """Args:
        include: application ids the round deploys.

    Returns:
        ``applications`` overrides that move each public port
        LAB_RESOLVER_PORT of these roles to LAB_REMAPPED_PORT; empty when
        none publishes it.
    """
    overrides: dict[str, Any] = {}
    for app_id in include:
        path = PROJECT_ROOT / "roles" / app_id / ROLE_FILE_META_SERVICES
        if not path.is_file():
            continue
        services = load_yaml_any(str(path))
        if not isinstance(services, dict):
            continue
        for entity, service in services.items():
            moved = {
                name: LAB_REMAPPED_PORT
                for name, port in _public_ports(service).items()
                if port == LAB_RESOLVER_PORT
            }
            if moved:
                app = overrides.setdefault(app_id, {"services": {}})
                app["services"][entity] = {"ports": {"public": moved}}
    return overrides
