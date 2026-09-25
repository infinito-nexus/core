"""Lookup `group_roles`: the roles of a role group in run_after order.

Returns one ``{'role': …, 'app': …}`` mapping per role, so a stage can loop
over the group instead of including a generated task file per group:

    loop: "{{ lookup('group_roles', 'web-app') }}"

`role` is the directory under ``roles/``, `app` the role's application_id --
the value the deployment whitelist and `application_allowed` speak in.

Passing ``inventory_groups`` (the ``groups`` magic variable) drops the roles no
host in the inventory carries, so they never enter the loop at all. That list
is identical on every host, which is the whole point: 8aea5a9b35 measured that
a per-host condition above the loop makes ansible insert blocks in host order
rather than loop order, after which svc-storage-nfs-client mounted an export
svc-storage-nfs-server had not deployed yet. Narrowing to a single host stays
in the body's ``when``, never here.
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
        inventory_groups = kwargs.get("inventory_groups")
        try:
            entries = [dict(entry) for entry in ordered_roles(roles_dir, group)]
        except Exception as exc:
            raise AnsibleError(f"group_roles: {exc}") from exc

        if inventory_groups is None:
            return [entries]
        return [[entry for entry in entries if inventory_groups.get(entry["app"])]]
