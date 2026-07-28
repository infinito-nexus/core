from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.lookup import LookupBase

LOOPBACK = "127.0.0.1"
NODE_GROUP = "svc-swarm-node"
MANAGER_GROUP = "svc-swarm-manager"


def resolve_smtp_host(variables: dict[str, Any], email: dict[str, Any]) -> Any:
    """Return the SMTP endpoint msmtp relays through.

    Args:
        variables: the play's variable namespace.
        email: the resolved ``lookup('email')`` mapping.

    Returns:
        The configured relay host, the loopback address, or a swarm manager.

    Outside the containerised test rig the configured relay is used unchanged.
    Inside it that relay domain has neither DNS nor a route: a host carrying the
    stack itself reaches mail on loopback, while a bare infra node has nothing
    listening there and has to enter through the manager's routing mesh.
    """
    relay = email.get("host")
    in_rig = _to_bool(email.get("external"), strict=False) and _to_bool(
        variables.get("DOCKER_IN_CONTAINER"), strict=False
    )
    if not in_rig:
        return relay

    if variables.get("DEPLOYMENT_MODE") == "compose" or NODE_GROUP in (
        variables.get("group_names") or []
    ):
        return LOOPBACK

    managers = (variables.get("groups") or {}).get(MANAGER_GROUP) or []
    return managers[0] if managers else relay


class LookupModule(LookupBase):
    """
    Usage:
      {{ lookup('smtp_host', email) }}

    SMTP endpoint for the msmtp relay config. Takes the resolved email mapping.
    """

    def run(self, terms, variables: dict[str, Any] | None = None, **kwargs):
        if len(terms or []) != 1:
            raise AnsibleError(
                "smtp_host: expected exactly 1 term: lookup('smtp_host', email)"
            )
        email = terms[0]
        if not isinstance(email, dict):
            raise AnsibleError("smtp_host: the term must be the email mapping.")
        variables = variables or getattr(self._templar, "available_variables", {}) or {}
        return [resolve_smtp_host(variables, email)]
