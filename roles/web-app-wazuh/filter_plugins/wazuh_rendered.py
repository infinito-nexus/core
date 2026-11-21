from __future__ import annotations

import base64
from typing import Any

from utils.cache.yaml import load_yaml_str

MAPPED_GROUPS = {
    "admin_group": "all_access",
    "analyst_group": "security_analyst",
    "readonly_group": "readonly_auditor",
}
DEFAULT_ROUTE = "uiSettings.overrides.defaultRoute"
API_FIELDS = {"api_url": "url", "api_port": "port", "api_username": "username"}


def _security(mapping: dict) -> dict:
    held = {}
    for field, role in MAPPED_GROUPS.items():
        backend_roles = (mapping.get(role) or {}).get("backend_roles") or []
        if backend_roles:
            held[field] = str(backend_roles[0])
    return held


def _dashboard(dashboards: dict, api: dict) -> dict:
    held = {}
    if DEFAULT_ROUTE in dashboards:
        held["default_route"] = str(dashboards[DEFAULT_ROUTE])
    hosts = api.get("hosts") or []
    host = next(iter(hosts[0].values()), {}) if hosts else {}
    for field, key in API_FIELDS.items():
        if key in host:
            held[field] = host[key]
    return held


def wazuh_rendered(results: Any) -> dict:
    """Return the managed values the security and dashboard files a previous deploy left hold.

    Args:
        results: the slurp loop results over ``roles_mapping.yml``,
            ``opensearch_dashboards.yml`` and ``wazuh.yml``.

    Returns:
        The forms ``security`` and ``dashboard`` of the role's meta/forms.yml,
        each field mapped to the value the file holds; a form whose files
        the slurp did not read is left out.
    """
    files = {
        result["item"]: load_yaml_str(base64.b64decode(result["content"]).decode())
        or {}
        for result in results or []
        if "content" in result
    }
    held = {}
    if "roles_mapping.yml" in files:
        held["security"] = _security(files["roles_mapping.yml"])
    if "opensearch_dashboards.yml" in files and "wazuh.yml" in files:
        held["dashboard"] = _dashboard(
            files["opensearch_dashboards.yml"], files["wazuh.yml"]
        )
    return held


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {"wazuh_rendered": wazuh_rendered}
