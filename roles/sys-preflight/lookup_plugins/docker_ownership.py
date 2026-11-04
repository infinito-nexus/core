"""Lookup ``docker_ownership``: the docker containers or volumes of a host
that do not belong to the entity of the role that declares them.

    {{ lookup('docker_ownership', kind, probe, group_names) }}

Args:
    kind: ``container`` or ``volume``.
    probe: the registered result of ``container ps --all`` or
        ``container volume ls``, formatted as
        ``<names>\\t<compose project label>\\t<stack namespace label>``.
    group_names: every group of the host, after the swarm auto-placement.

Returns:
    The messages of :func:`utils.preflight.ownership.labelled_ownership_errors`
    for every name a role the deploy may run on the host declares: the
    ``services.<key>.name`` of its containers, or the docker name of each
    ``type: volume`` entry of its ``meta/volumes.yml`` (the ``name`` field,
    else ``<entity>_<key>`` as compose names it). A role whose
    ``meta/networks.yml`` sets ``local.launcher: true`` starts its containers
    with its own launcher outside any compose project, so its container
    names carry no label to compare.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.preflight.context import DeployClosureContext, deploy_closure_context
from utils.preflight.ownership import labelled_ownership_errors, parse_labelled
from utils.roles.entity.name import entity_name

_KINDS = ("container", "volume")


def _container_names(context: DeployClosureContext, role: str) -> list[str]:
    if context.config(role, "networks.local.launcher", False) is True:
        return []
    services = (context.applications.get(role) or {}).get("services") or {}
    names = []
    for key, entry in sorted(services.items()):
        if isinstance(entry, dict) and "name" in entry:
            name = str(context.config(role, f"services.{key}.name", "") or "").strip()
            if name:
                names.append(name)
    return names


def _volume_names(context: DeployClosureContext, role: str) -> list[str]:
    registry = context.lookup("volume", role) or {}
    return [
        str(entry.get("name") or f"{entity_name(role)}_{key}")
        for key, entry in sorted(registry.items())
        if isinstance(entry, dict) and entry.get("type", "volume") == "volume"
    ]


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        if not terms or len(terms) != 3:
            raise AnsibleError(
                "lookup('docker_ownership', kind, probe, group_names) expects exactly 3 terms"
            )
        kind, probe, group_names = terms
        if kind not in _KINDS:
            raise AnsibleError(
                f"docker_ownership: kind must be one of {', '.join(_KINDS)}, got {kind!r}"
            )
        try:
            objects = parse_labelled(probe["stdout"])
        except (KeyError, TypeError, ValueError) as exc:
            raise AnsibleError(
                f"docker_ownership: unparsable {kind} probe: {exc}"
            ) from exc
        try:
            context = deploy_closure_context(self, variables, group_names)
        except (TypeError, ValueError) as exc:
            raise AnsibleError(f"docker_ownership: {exc}") from exc

        names_of = _container_names if kind == "container" else _volume_names
        declared: dict[str, list[tuple[str, str]]] = {}
        for role in context.roles:
            for name in names_of(context, role):
                declared.setdefault(name, []).append((role, entity_name(role)))
        return [labelled_ownership_errors(kind, objects, declared)]
