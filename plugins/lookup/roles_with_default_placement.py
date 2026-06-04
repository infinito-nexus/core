"""List roles whose entity in meta/services.yml declares a default_placement.

Used by the constructor's auto-place add_host loop to wire shared single-host
services (openresty, central DBs, registries) onto the manager when the
operator did not list them explicitly. Operator inventory entries win:
auto-placement only fires when groups[role_id] is empty.

    lookup('roles_with_default_placement', 'manager')
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils import PROJECT_ROOT
from utils.cache.yaml import load_yaml_any
from utils.roles.entity_name import get_entity_name
from utils.roles.mapping import ROLE_FILE_META_SERVICES


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        terms = terms or []
        if len(terms) != 1:
            raise AnsibleError(
                "roles_with_default_placement: expected exactly 1 term, "
                "the placement value (e.g. 'manager')"
            )

        wanted_placement = str(terms[0])
        roles_dir = PROJECT_ROOT / "roles"

        if not roles_dir.is_dir():
            return [[]]

        matches: list[str] = []
        for role_dir in sorted(roles_dir.iterdir()):
            if not role_dir.is_dir():
                continue
            meta = role_dir / ROLE_FILE_META_SERVICES
            if not meta.is_file():
                continue
            data = load_yaml_any(str(meta), default_if_missing={}) or {}
            if not isinstance(data, dict):
                continue
            entity_name = get_entity_name(role_dir.name)
            if not entity_name:
                continue
            service_entry = data.get(entity_name)
            if not isinstance(service_entry, dict):
                continue
            if str(service_entry.get("default_placement", "")) == wanted_placement:
                matches.append(role_dir.name)

        return [matches]
