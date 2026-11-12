from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils import PROJECT_ROOT
from utils.roles.entity.name import get_entity_name
from utils.security.engine import ROLE, SCANNERS
from utils.security.suppressions import SuppressionError, role_suppressions

ROLES_DIR = PROJECT_ROOT / "roles"


def collect(group_names: list[str]) -> dict[str, dict]:
    """Return the suppressions the scan applies on this node.

    Args:
        group_names: the deployed role ids.

    Returns:
        ``{"containers": {entity: {service: [entry]}}, "host": {engine:
        [entry]}}`` where an entry is ``{"id", "image_tag", "until"}``. The
        entity is the compose project and swarm stack name, so a role's
        suppressions reach only its own containers. The host takes the
        ``id`` entries of the engine services only; their ``image_tag``
        entries cover the engine's own image.
    """
    containers: dict[str, dict[str, list[dict[str, str]]]] = {}
    for role in sorted(set(group_names)):
        entity = get_entity_name(role)
        declared = role_suppressions(ROLES_DIR, role)
        if entity and declared:
            containers[entity] = {
                service: [entry.as_json() for entry in entries]
                for service, entries in declared.items()
            }
    own = role_suppressions(ROLES_DIR, ROLE)
    host = {
        engine: [entry.as_json() for entry in entries if entry.id]
        for engine, entries in own.items()
        if engine in SCANNERS
    }
    return {"containers": containers, "host": host}


class LookupModule(LookupBase):
    """``lookup('cve_suppressions', group_names=<role ids>)``, see :func:`collect`."""

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, dict]]:
        group_names = kwargs.get("group_names")
        if not isinstance(group_names, (list, tuple)):
            raise AnsibleError(
                "cve_suppressions: group_names must be a list of role ids"
            )
        try:
            return [collect([str(name) for name in group_names])]
        except SuppressionError as exc:
            raise AnsibleError(f"cve_suppressions: {exc}") from exc
