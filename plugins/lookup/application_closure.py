"""Lookup ``application_closure``: roles reachable from a seed application set.

Walks the same edges the constructor's role set is built from, so a
whitelist-scoped deploy and the full-inventory deploy agree on what a role
depends on. The traversal itself lives in
``utils/roles/applications/in_group_deps``; this only exposes it to Ansible.

    {{ lookup('application_closure', ['web-app-snipe-it']) }}

Returns the seed roles plus every role reachable through ``meta/main.yml``
dependencies and declared service edges, transitively. An empty seed yields an
empty list, which callers read as "no scoping requested".
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils import PROJECT_ROOT
from utils.roles.applications.in_group_deps import reachable_roles


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[str]]:
        seeds: list[str] = []
        for term in terms or []:
            if isinstance(term, (list, tuple, set)):
                seeds.extend(str(entry) for entry in term)
            elif term:
                seeds.append(str(term))

        if not seeds:
            return [[]]

        roles_dir = kwargs.get("roles_dir") or str(PROJECT_ROOT / "roles")
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}

        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]
        try:
            included = reachable_roles(
                applications,
                seeds,
                roles_dir=roles_dir,
                project_root=str(PROJECT_ROOT),
            )
        except (TypeError, ValueError) as exc:
            raise AnsibleError(f"application_closure: {exc}") from exc

        return [sorted(included | set(seeds))]
