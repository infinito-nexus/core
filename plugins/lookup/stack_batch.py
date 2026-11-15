from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.application_allowed import application_allowed
from utils import PROJECT_ROOT
from utils.cache.files import read_text
from utils.cache.yaml import load_yaml_any
from utils.roles.applications.services.preload import preloaded
from utils.roles.applications.services.registry import (
    build_service_registry_from_roles_dir,
    ordered_primary_service_entries,
)
from utils.roles.mapping import ROLE_FILE_META_SERVICES
from utils.roles.order import ordered_roles
from utils.roles.stage import stage_groups

if TYPE_CHECKING:
    from collections.abc import Callable

STACK_ROLE = "svc-stack"
BRIDGE = Path("tasks/utils/stack.yml")
CANONICAL_BRIDGE = Path(STACK_ROLE) / "files/bridge.yml"
STACK_META = Path(ROLE_FILE_META_SERVICES)


def item_errors(roles_dir: Path, role: str) -> list[str]:
    """Args:
        roles_dir: the roles directory.
        role: a role that ships a stack bridge.

    Returns:
        every reason the role cannot join the front batch, empty when it can.
    """
    errors = []
    if read_text(str(roles_dir / role / BRIDGE)) != read_text(
        str(roles_dir / CANONICAL_BRIDGE)
    ):
        errors.append(f"{BRIDGE} differs from roles/{CANONICAL_BRIDGE}")
    try:
        stack = (load_yaml_any(str(roles_dir / role / STACK_META)) or {}).get("stack")
    except yaml.YAMLError as exc:
        return [*errors, f"{STACK_META} does not parse: {exc}"]
    if not (
        isinstance(stack, dict)
        and stack.get("enabled") is True
        and stack.get("shared") is True
    ):
        errors.append(
            f"{STACK_META} does not declare stack enabled and shared as literal true"
        )
    return errors


def plan(
    roles_dir: Path,
    ordered_services: list[dict[str, Any]],
    required_ids: list[str],
    closure: list[str],
    group_names: list[str],
    inventory_groups: dict[str, Any],
    whitelist: list[str],
    *,
    tls_mode: Callable[[str], str],
) -> list[dict[str, Any]]:
    """Args:
        roles_dir: the roles directory.
        ordered_services: the shared services in loader order, each with id and role.
        required_ids: the service keys some deployed role requires.
        closure: the deployment whitelist's dependency closure.
        group_names: the inventory groups of the current host.
        inventory_groups: the groups magic variable.
        whitelist: the deployment whitelist.
        tls_mode: the TLS mode of an application id, ``off`` without a domain.

    Returns:
        one item per bridged application this host enters after svc-stack's
        slot, in entry order: the shared services the loader preloads, then
        the server roles the deployment allows. A preloaded service that is
        also a server role keeps its preload item. Each item carries its id,
        role, phase, TLS mode and admission errors.
    """
    roles = [entry["role"] for entry in ordered_services]
    after = (
        ordered_services[roles.index(STACK_ROLE) + 1 :] if STACK_ROLE in roles else []
    )
    entries = [
        (entry["role"], entry["role"], "preload")
        for entry in after
        if preloaded(entry["id"], entry["role"], required_ids, group_names, closure)
    ]
    for group in stage_groups("server"):
        entries += [
            (entry["app"], entry["role"], "server")
            for entry in ordered_roles(str(roles_dir), group)
            if inventory_groups.get(entry["app"])
            and application_allowed(entry["app"], group_names, whitelist)
        ]
    first: dict[str, tuple[str, str]] = {}
    for app, role, phase in entries:
        first.setdefault(app, (role, phase))
    return [
        item(roles_dir, app, role, phase, tls_mode=tls_mode)
        for app, (role, phase) in first.items()
        if (roles_dir / role / BRIDGE).is_file()
    ]


def item(
    roles_dir: Path,
    app: str,
    role: str,
    phase: str,
    *,
    tls_mode: Callable[[str], str],
) -> dict[str, Any]:
    """Args:
        roles_dir: the roles directory.
        app: the application id the role is entered with.
        role: a role that ships a stack bridge.
        phase: the stack phase its front renders in: preload, server or late.
        tls_mode: the TLS mode of an application id, ``off`` without a domain.

    Returns:
        the batch item of the role: its id, role, phase, TLS mode and
        admission errors.
    """
    return {
        "id": app,
        "role": role,
        "phase": phase,
        "tls_mode": tls_mode(app),
        "errors": item_errors(roles_dir, role),
    }


class LookupModule(LookupBase):
    def run(self, terms, variables=None, **kwargs):
        """Args:
            terms: empty for the plan of the host, or the one application id
                whose front the batch did not plan.
            variables: the task variables.
            kwargs: ``roles_dir``, and ``role``, the role entered with that
                application id.

        Returns:
            the plan of the host, or the one late item of that application id.
        """
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        roles_dir = Path(kwargs.get("roles_dir") or PROJECT_ROOT / "roles")

        def lookup(name, *terms_, **kwargs_):
            return lookup_loader.get(
                name, loader=self._loader, templar=getattr(self, "_templar", None)
            ).run(list(terms_), variables=vars_, **kwargs_)

        domains = lookup("domains")[0]

        def tls_mode(app: str) -> str:
            return str(lookup("tls", app, "mode")[0]) if app in domains else "off"

        if terms:
            return [
                [item(roles_dir, terms[0], kwargs["role"], "late", tls_mode=tls_mode)]
            ]
        ordered = ordered_primary_service_entries(
            build_service_registry_from_roles_dir(roles_dir), roles_dir
        )
        required_ids = [
            entry["id"]
            for entry in lookup(
                "service", [entry["id"] for entry in ordered], roles_dir=str(roles_dir)
            )
            if entry.get("required")
        ]
        whitelist = list(lookup("deployment")[0].get("whitelist") or [])
        return [
            plan(
                roles_dir,
                ordered,
                required_ids,
                lookup("application_closure", whitelist)[0],
                list(vars_["group_names"]),
                dict(vars_["groups"]),
                whitelist,
                tls_mode=tls_mode,
            )
        ]
