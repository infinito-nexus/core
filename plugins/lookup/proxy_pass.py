"""Lookup ``proxy_pass``: thin wrapper emitting the mode-aware directive via
:func:`utils.networks.proxy.resolve_upstream` + :func:`render_proxy_pass`."""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.networks.proxy import render_proxy_pass, resolve_upstream


def _as_str(value: Any) -> str:
    return "" if value is None else str(value).strip()


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
        deployment_mode = str(raw_mode).strip()

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]

        try:
            authority = resolve_upstream(
                applications,
                application_id,
                service_key,
                port_kind,
                deployment_mode,
                local_port=_as_str(kwargs.get("local_port")),
                internal_port=_as_str(kwargs.get("internal_port")),
            )
            return [
                render_proxy_pass(
                    authority, deployment_mode, tail=tail, location=location
                )
            ]
        except ValueError as exc:
            raise AnsibleError(f"proxy_pass: {exc}") from exc
