"""Lookup `ca_injected`: whether the self-signed root CA is mounted into an
application's containers.

    {{ lookup('ca_injected', application_id) }}

Anything that reads the mounted ``CA_TRUST.inject_cert_container`` must ask this
lookup, or it points at a path that was never mounted.

An application with a domain and TLS of its own gets the CA when its resolved
TLS mode is self-signed. Otherwise it gets it only when one of its services
declares ``ca_client: true`` and the SSO issuer application it calls resolves
TLS enabled and self-signed.

Those three ask whether the application is *served* over the self-signed CA.
An application that only *calls* one resolves no mode of its own and would be
skipped, so a service may declare ``ca_client: true`` and be answered on the
deployment's TLS mode, or on an SSO issuer that resolves self-signed TLS.
Either peer is enough: the object store a container signs media against and
the issuer it authenticates through are different hosts, and answering for
only one leaves the other's handshake unverifiable. Without the CA such a
container verifies against an empty trust store and fails every outbound call
at the TLS handshake.

Resolving no mode of its own covers two shapes, and the declaration answers
for both: an application with no domain at all, and one whose own TLS is
disabled. The second is the onion case, where ``resolve_enabled`` returns
False for a ``.onion`` primary; the application has a domain, is served
without TLS, and still needs the CA for its outbound calls. An application
whose own TLS *is* enabled keeps deciding on its own resolved mode, which may
override the deployment default, so the declaration never answers for it.

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
from utils.tls_common import (
    AVAILABLE_FLAVORS,
    as_str,
    issuer_applications,
    require,
    resolve_primary_domain_from_app,
)

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

        def _declares_ca_client() -> bool:
            services = _run("config", [application_id, "services", {}]) or {}
            return any(
                _to_bool(service.get("ca_client", False))
                for service in services.values()
                if isinstance(service, dict)
            )

        def _on_the_deployment_mode() -> bool:
            mode = as_str(require(variables or {}, "TLS_MODE", str))
            if mode not in AVAILABLE_FLAVORS:
                raise AnsibleError(
                    f"ca_injected: TLS_MODE must be one of "
                    f"{sorted(AVAILABLE_FLAVORS)}, got '{mode}'"
                )
            return mode == SELF_SIGNED_MODE

        def _an_issuer_is_self_signed() -> bool:
            return any(
                _to_bool(_run("tls", [peer, "enabled"]))
                and _run("tls", [peer, "mode"]) == SELF_SIGNED_MODE
                for peer in issuer_applications()
            )

        domains = _run("domains", [])
        own_domain = (
            resolve_primary_domain_from_app(
                domains, application_id, err_prefix="ca_injected"
            )
            if has_domain(domains, application_id)
            else ""
        )
        own_tls = bool(own_domain) and _to_bool(_run("tls", [own_domain, "enabled"]))
        if own_tls and _run("tls", [own_domain, "mode"]) == SELF_SIGNED_MODE:
            return [True]
        if not _declares_ca_client():
            return [False]
        if _an_issuer_is_self_signed():
            return [True]
        if own_tls:
            return [False]
        return [_on_the_deployment_mode()]
