from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import get
from utils.roles.applications.status_codes import declared_status_codes

_CHECKER_ACCEPTS_BELOW = 300


def _domains(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, Mapping):
        out: list[str] = []
        for entry in value.values():
            out.extend(_domains(entry))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for entry in value:
            out.extend(_domains(entry))
        return out
    return []


class LookupModule(LookupBase):
    """Return ``<domain>=<code>[,<code>]`` for every declared non-2xx status.

    The checker treats anything outside 2xx as unreachable, so a vhost that
    serves a 4xx by design needs its code named. Naming it keeps the page
    under CSP inspection, which excluding the domain would not.

    The declaration is per vhost: ``server.status_codes`` is keyed like
    ``domains.canonical``, so two domains of one role can differ.
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        applications = lookup_loader.get(
            "applications",
            loader=self._loader,
            templar=getattr(self, "_templar", None),
        ).run(
            [],
            variables=variables
            or getattr(self._templar, "available_variables", {})
            or {},
        )[0]

        if not isinstance(applications, Mapping):
            return [[]]

        accepted: dict[str, set[int]] = {}
        for app_id in applications:
            domains = _domains(
                get(applications, app_id, "domains.canonical", strict=False, default=[])
            ) + _domains(
                get(applications, app_id, "domains.aliases", strict=False, default=[])
            )
            for domain in domains:
                codes = {
                    code
                    for code in declared_status_codes(applications, app_id, domain)
                    if code >= _CHECKER_ACCEPTS_BELOW
                }
                if codes:
                    accepted.setdefault(domain, set()).update(codes)

        return [
            [
                f"{domain}={','.join(str(code) for code in sorted(codes))}"
                for domain, codes in sorted(accepted.items())
            ]
        ]
