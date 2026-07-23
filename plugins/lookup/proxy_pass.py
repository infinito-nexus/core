"""Lookup ``proxy_pass``: thin wrapper emitting the mode-aware directive via
:func:`utils.networks.proxy.resolve_upstream` + :func:`render_proxy_pass`."""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.proxy import render_proxy_pass, resolve_upstream
from utils.roles.applications.config import get as get_app_conf
from utils.templating.ansible import _trust_as_template


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _as_bool(value: Any) -> bool:
    return _as_str(value).lower() in ("true", "1", "yes")


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[str]:
        if not terms:
            raise AnsibleError("proxy_pass lookup requires the application_id term")

        application_id = _as_str(terms[0])
        if not application_id:
            raise AnsibleError("proxy_pass: application_id must be non-empty")

        service_key = _as_str(terms[1]) if len(terms) > 1 else ""
        port_kind = _as_str(terms[2]) if len(terms) > 2 else "http"
        if not port_kind:
            port_kind = "http"
        tail = _as_str(kwargs.get("tail")) or "request"
        location = _as_str(kwargs.get("location")) or "/"

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)

        raw_mode = vars_.get("DEPLOYMENT_MODE", "compose")
        if templar is not None:
            with contextlib.suppress(Exception):
                raw_mode = templar.template(raw_mode)
        real_deployment_mode = str(raw_mode).strip()

        mode_force = vars_.get("compose_mode_force", "")
        if templar is not None:
            with contextlib.suppress(Exception):
                mode_force = templar.template(mode_force)
        deployment_mode = _as_str(mode_force) or real_deployment_mode

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        force_bridge_raw = get_app_conf(
            applications=applications,
            application_id=application_id,
            config_path="networks.local.force_bridge",
            strict=False,
            default=False,
            skip_missing_app=True,
        )
        if templar is not None and isinstance(force_bridge_raw, str):
            with contextlib.suppress(Exception):
                force_bridge_raw = templar.template(
                    _trust_as_template(force_bridge_raw)
                )
        if isinstance(force_bridge_raw, str) and "{{" in force_bridge_raw:
            raise AnsibleError(
                f"proxy_pass: networks.local.force_bridge for "
                f"{application_id!r} did not template: {force_bridge_raw!r}"
            )
        # Exception: keyed on real_deployment_mode, not deployment_mode - a
        # force_bridge app rewrites the latter to 'compose' via
        # compose_mode_force, which would silently no-op the host-gateway path.
        host_gateway = _as_bool(force_bridge_raw) and real_deployment_mode == "swarm"

        try:
            authority = resolve_upstream(
                applications,
                application_id,
                service_key,
                port_kind,
                deployment_mode,
                local_port=_as_str(kwargs.get("local_port")),
                internal_port=_as_str(kwargs.get("internal_port")),
                host_gateway=host_gateway,
            )
            return [
                render_proxy_pass(
                    authority,
                    deployment_mode,
                    tail=tail,
                    location=location,
                    host_gateway=host_gateway,
                )
            ]
        except ValueError as exc:
            raise AnsibleError(f"proxy_pass: {exc}") from exc
