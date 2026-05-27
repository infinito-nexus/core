from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.plugins.lookup import LookupBase

from utils.cache.applications import get_merged_applications
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


def _has_code_ge_400(codes: Any) -> bool:
    if codes is None:
        return False
    if not isinstance(codes, (list, tuple, set)):
        codes = [codes]
    for c in codes:
        try:
            n = int(c)
        except (TypeError, ValueError):
            continue
        if n >= 400:
            return True
    return False


def _selection_from(group_names: Any) -> set[str]:
    if isinstance(group_names, (list, set, tuple)):
        return {str(x) for x in group_names if str(x)}
    if isinstance(group_names, str):
        return {g.strip() for g in group_names.split(",") if g.strip()}
    return set()


class LookupModule(LookupBase):
    """Return domains the CSP probe should skip.

    Skips canonical + alias domains of every selected application whose
    ``server.status_codes.default`` declares any HTTP code >= 400
    (e.g. federation-only roles that legitimately serve 4xx at ``/``).
    """

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        applications = get_merged_applications(
            variables=variables
            or getattr(self._templar, "available_variables", {})
            or {},
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        if not isinstance(applications, Mapping):
            return [[]]

        selection = _selection_from(kwargs.get("group_names"))

        skip: set[str] = set()
        for app_id in applications:
            if selection and app_id not in selection:
                continue

            default = get(
                applications,
                app_id,
                "server.status_codes.default",
                strict=False,
                default=None,
            )
            if not _has_code_ge_400(default):
                continue

            canonical = get(
                applications,
                app_id,
                "server.domains.canonical",
                strict=False,
                default=[],
            )
            aliases = get(
                applications,
                app_id,
                "server.domains.aliases",
                strict=False,
                default=[],
            )
            for d in _to_list(canonical) + _to_list(aliases):
                if d:
                    skip.add(d)

        return [sorted(skip)]
