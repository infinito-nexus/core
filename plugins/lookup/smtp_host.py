from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.lookup import LookupBase

from utils.networks.lookup_context import resolve_var

LOOPBACK = "127.0.0.1"
CONTAINER_HOST_ALIAS = "host.docker.internal"
NODE_GROUP = "svc-swarm-node"
MANAGER_GROUP = "svc-swarm-manager"


def resolve_smtp_host(
    variables: dict[str, Any], email: dict[str, Any], *, in_container: bool = False
) -> Any:
    """Return the SMTP endpoint msmtp relays through.

    Args:
        variables: the play's variable namespace.
        email: the resolved ``lookup('email')`` mapping.
        in_container: the rendered config is mounted INTO a container rather
            than read by the host's own msmtp.

    Returns:
        The configured relay host, the loopback address, the container's alias
        for its host, or a swarm manager.

    Outside the containerised test rig the configured relay is used unchanged.
    Inside it that relay domain has neither DNS nor a route: a host carrying the
    stack itself reaches mail on loopback, while a bare infra node has nothing
    listening there and has to enter through the manager's routing mesh.

    ``in_container`` exists because one template serves two consumers. The host's
    /root/.msmtprc is read by the host and loopback is right for it; the copy
    mounted at /etc/msmtprc is read inside a container, where 127.0.0.1 is that
    container's own loopback and nothing listens on it. Such a service must also
    emit ``lookup('container_extra_hosts')`` so the alias resolves.
    """
    relay = email.get("host")
    in_rig = _to_bool(email.get("external"), strict=False) and _to_bool(
        variables.get("DOCKER_IN_CONTAINER"), strict=False
    )
    if not in_rig:
        return relay

    if in_container:
        return CONTAINER_HOST_ALIAS

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
      {{ lookup('smtp_host', email, in_container=true) }}

    SMTP endpoint for the msmtp relay config. Takes the resolved email mapping.
    Pass in_container=true when the rendered file is mounted into a container
    instead of being read by the host's own msmtp.
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
        in_container = _to_bool(kwargs.get("in_container", False), strict=False)
        templar = getattr(self, "_templar", None)
        variables = dict(variables)
        for key in ("DOCKER_IN_CONTAINER", "DEPLOYMENT_MODE"):
            if key in variables:
                variables[key] = resolve_var(templar, variables[key])
        return [resolve_smtp_host(variables, email, in_container=in_container)]
