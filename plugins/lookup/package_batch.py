"""Lookup ``package_batch``: the package ids a host installs in one run at
deploy start.

    {{ lookup('package_batch', group_names) }}

The terms are every group of the host, after the swarm auto-placement, so a
role the service loader reaches on this host through any whitelist is covered. They are widened to
every role the deploy may run on the host
(:func:`utils.roles.invocations.deploy_closure`), and the sorted ids the
batch installs for those roles (:func:`utils.packages.batch.batch_ids`) are
returned.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

from utils import PROJECT_ROOT
from utils.packages.batch import batch_ids
from utils.packages.schema import PackagesShapeError
from utils.roles.invocations import deploy_closure
from utils.roles.validation.invokable import types_from_group_names


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

        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        group_names = [str(group) for group in vars_["group_names"]]
        applications = lookup_loader.get(
            "applications", loader=self._loader, templar=getattr(self, "_templar", None)
        ).run([], variables=vars_)[0]
        try:
            roles = deploy_closure(
                applications,
                seeds,
                project_root=PROJECT_ROOT,
                host_types=types_from_group_names(group_names),
                group_names=group_names,
            )
            return [batch_ids(roles, PROJECT_ROOT)]
        except (PackagesShapeError, TypeError, ValueError) as exc:
            raise AnsibleError(f"package_batch: {exc}") from exc
