from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ansible.plugins.loader import lookup_loader
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


def _selection_from(group_names: Any) -> set[str]:
    if isinstance(group_names, (list, set, tuple)):
        return {str(x) for x in group_names if str(x)}
    if isinstance(group_names, str):
        return {g.strip() for g in group_names.split(",") if g.strip()}
    return set()


class LookupModule(LookupBase):
    """Return the full redirect-mapping list for the www-redirect helper.

    For every selected application, iterate ``server.domains.canonical`` and
    ``server.domains.aliases`` and emit a ``{source, target}`` 301-mapping:
      * if the entry already begins with ``www.``: source = entry,
        target = entry without the ``www.`` prefix,
      * otherwise: source = ``www.<entry>``, target = entry.

    In addition, when ``DOMAIN_HOMEPAGE`` is set in the playbook variables,
    the role's own canonical (resolved via ``lookup('domain', 'web-opt-rdr-www')``)
    is appended as a 301-mapping with ``DOMAIN_HOMEPAGE`` as target.

    The deployed-app selection is resolved internally via the ``deployment``
    lookup. Tests can override it by passing ``group_names=[...]`` explicitly.
    """

    def _resolve_deployed(self, variables: dict[str, Any] | None) -> list[str] | None:
        dep_plugin = lookup_loader.get(
            "deployment",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        )
        if dep_plugin is None:
            return None
        result = dep_plugin.run([], variables=variables)
        if result and isinstance(result[0], Mapping):
            return list(result[0].get("deployed") or [])
        return None

    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[dict[str, str]]]:
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = get_merged_applications(
            variables=vars_,
            roles_dir=kwargs.get("roles_dir"),
            templar=getattr(self, "_templar", None),
        )

        if not isinstance(applications, Mapping):
            return [[]]

        if "group_names" in kwargs:
            selection = _selection_from(kwargs["group_names"])
        else:
            selection = _selection_from(self._resolve_deployed(vars_))

        seen: set[tuple[str, str]] = set()
        mappings: list[dict[str, str]] = []

        for app_id in sorted(applications):
            if selection and app_id not in selection:
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
                if not d:
                    continue
                if d.startswith("www."):
                    source, target = d, d[4:]
                else:
                    source, target = f"www.{d}", d
                key = (source, target)
                if key in seen:
                    continue
                seen.add(key)
                mappings.append({"source": source, "target": target})

        domain_homepage = vars_.get("DOMAIN_HOMEPAGE")
        role_id = "web-opt-rdr-www"
        if (
            isinstance(domain_homepage, str)
            and domain_homepage
            and role_id in applications
        ):
            domain_plugin = lookup_loader.get(
                "domain",
                loader=getattr(self, "_loader", None),
                templar=getattr(self, "_templar", None),
            )
            if domain_plugin is not None:
                role_canonical = domain_plugin.run([role_id], variables=vars_)[0]
                if isinstance(role_canonical, str) and role_canonical:
                    key = (role_canonical, domain_homepage)
                    if key not in seen:
                        seen.add(key)
                        mappings.append({"source": key[0], "target": key[1]})

        mappings.sort(key=lambda m: (m["source"], m["target"]))
        return [mappings]
