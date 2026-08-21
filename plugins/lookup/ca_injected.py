"""Lookup `ca_injected`: whether the self-signed root CA is mounted into an
application's containers.

    {{ lookup('ca_injected', application_id) }}

The CA override that bind-mounts ``CA_TRUST.inject_cert_container`` is emitted
under three conditions, and anything that reads the mounted file must ask the
same three or it will point at a path that was never mounted. The conditions
lived as four hand-copied expressions - both `sys-svc-compose` handlers,
`sys-svc-compose-ca/vars/main.yml` and the msmtp template - which is one copy
per place that can drift.

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

        if not has_domain(_run("domains", []), application_id):
            return [False]
        if not _to_bool(_run("tls", [application_id, "enabled"])):
            return [False]
        return [_run("tls", [application_id, "mode"]) == SELF_SIGNED_MODE]
