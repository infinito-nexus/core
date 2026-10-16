"""Lookup `ca_injected`: whether the self-signed root CA is mounted into an
application's containers.

    {{ lookup('ca_injected', application_id) }}

Anything that reads the mounted ``CA_TRUST.inject_cert_container`` must ask this
lookup, or it points at a path that was never mounted.

An application with a domain and TLS of its own gets the CA when its resolved
TLS mode is self-signed. Otherwise it gets it only when one of its services
declares ``ca_client: true`` and the SSO issuer application it calls resolves
TLS enabled and self-signed.

Returns a plain bool, so callers read as a predicate:

    when: lookup('ca_injected', application_id)
    {{ CA_TRUST.inject_cert_container if lookup('ca_injected', application_id) else ... }}
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.module_utils.parsing.convert_bool import boolean as _to_bool
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from plugins.filter.has.domain import has_domain
from utils.tls_common import issuer_applications

SELF_SIGNED_MODE = "self_signed"


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[bool]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "ca_injected lookup requires exactly one term: the application id"
            )
        templar = getattr(self, "_templar", None)
        raw = templar.template(terms[0]) if templar is not None else terms[0]
        application_id = str(raw).strip()
        if not application_id:
            raise AnsibleError("ca_injected lookup: application id must be non-empty")

        def _run(name: str, args: list[Any]) -> Any:
            return lookup_loader.get(name, loader=self._loader, templar=templar).run(
                args, variables=variables or {}
            )[0]

        if (
            has_domain(_run("domains", []), application_id)
            and _to_bool(_run("tls", [application_id, "enabled"]))
            and _run("tls", [application_id, "mode"]) == SELF_SIGNED_MODE
        ):
            return [True]

        services = _run("config", [application_id, "services", {}]) or {}
        if not any(
            _to_bool(service.get("ca_client", False))
            for service in services.values()
            if isinstance(service, dict)
        ):
            return [False]
        return [
            any(
                _to_bool(_run("tls", [peer, "enabled"]))
                and _run("tls", [peer, "mode"]) == SELF_SIGNED_MODE
                for peer in issuer_applications()
            )
        ]
