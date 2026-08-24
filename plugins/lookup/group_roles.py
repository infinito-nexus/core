"""Lookup `group_roles`: the roles of a role group in run_after order.

Returns one ``{'role': …, 'app': …}`` mapping per role, so a stage can loop
over the group instead of including a generated task file per group:

    loop: "{{ lookup('group_roles', 'web-app') }}"

`role` is the directory under ``roles/``, `app` the role's application_id --
the value the deployment whitelist and `application_allowed` speak in.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.roles.order import ordered_roles


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[list[dict[str, str]]]:
        if not terms or len(terms) != 1:
            raise AnsibleError(
                "group_roles lookup requires exactly one term: the group"
            )

        group = str(terms[0]).strip()
        if not group:
            raise AnsibleError("group_roles lookup: the group must not be empty")

        roles_dir = str(kwargs.get("roles_dir") or Path.cwd() / "roles")
        try:
            return [[dict(entry) for entry in ordered_roles(roles_dir, group)]]
        except Exception as exc:
            raise AnsibleError(f"group_roles: {exc}") from exc
