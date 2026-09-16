from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils.roles.applications.config import get


def _to_list(x: Any) -> list[str]:
    if x is None:
        return []
    if isinstance(x, str):
        return [x]
    if isinstance(x, (list, tuple, set)):
        out: list[str] = []
        for v in x:
            if isinstance(v, (list, tuple, set)):
                out.extend(_to_list(v))
            elif isinstance(v, str):
                out.append(v)
            elif isinstance(v, Mapping):
                out.extend(_to_list(list(v.values())))
        return out
    if isinstance(x, Mapping):
        out = []
        for v in x.values():
            out.extend(_to_list(v))
        return out
    return []


def _selection_from(group_names: Any) -> set[str]:
    if isinstance(group_names, (list, set, tuple)):
        return {str(x) for x in group_names if str(x)}
    if isinstance(group_names, str):
        return {g.strip() for g in group_names.split(",") if g.strip()}
    return set()


class LookupModule(LookupBase):
    """Return domains the CSP probe should skip.

    Skips canonical domains owned by a disabled service: a
    service entry may declare ``domains: [<canonical key>, ...]``; when its
    ``enabled`` resolves falsy those canonicals get no vhost (e.g. the
    seaweedfs filer/master frontend on an onion node), so probing them can
    only fail.
    """

    def _service_disabled_domains(self, applications: Mapping, app_id: str) -> set[str]:
        services = get(applications, app_id, "services", strict=False, default={})
        canonical = get(
            applications, app_id, "server.domains.canonical", strict=False, default={}
        )
        if not isinstance(services, Mapping) or not isinstance(canonical, Mapping):
            return set()
        templar = getattr(self, "_templar", None)
        skip: set[str] = set()
        for svc in services.values():
            if not isinstance(svc, Mapping) or "domains" not in svc:
                continue
            enabled = svc.get("enabled", True)
            if isinstance(enabled, str) and templar is not None:
                enabled = templar.template(enabled)
            if enabled:
                continue
            for key in _to_list(svc.get("domains")):
                domain = canonical.get(key)
                if isinstance(domain, str) and "{{" in domain and templar is not None:
                    domain = templar.template(domain)
                if isinstance(domain, str) and domain:
                    skip.add(domain)
        return skip

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

        selection = _selection_from(kwargs.get("group_names"))

        skip: set[str] = set()
        for app_id in applications:
            if not selection or app_id in selection:
                skip |= self._service_disabled_domains(applications, app_id)

        return [sorted(skip)]
