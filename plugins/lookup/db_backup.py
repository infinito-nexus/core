"""Lookup `db_backup`: the backup view of the database HA instance model.

    lookup('db_backup', 'role')                          # the backup role id
    lookup('db_backup', 'hosts')                         # HA instance hosts
    lookup('db_backup', 'local', bin_dir=DIR_BIN)        # instances on inventory_hostname
    lookup('db_backup', 'local', bin_dir=DIR_BIN, host='mgr-02')

Returns ``utils.roles.db.backup.ha_instance_hosts`` or
``utils.roles.db.backup.local_backup_instances``.
"""

from __future__ import annotations

import contextlib
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.roles.db.backup import (
    BACKUP_ROLE,
    ha_instance_hosts,
    local_backup_instances,
)
from utils.roles.db.instances import DbInstancesError

_KINDS = ("role", "hosts", "local")


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        if len(terms) != 1 or terms[0] not in _KINDS:
            raise AnsibleError(f"db_backup: expected one term out of {_KINDS}")
        if terms[0] == "role":
            return [BACKUP_ROLE]
        vars_ = variables or getattr(self._templar, "available_variables", {}) or {}
        templar = getattr(self, "_templar", None)
        mode = vars_.get("DEPLOYMENT_MODE", "compose")
        if templar is not None:
            with contextlib.suppress(Exception):
                mode = templar.template(mode)
        mode = str(mode).strip()
        groups = vars_.get("groups", {}) or {}
        try:
            if terms[0] == "hosts":
                return [ha_instance_hosts(groups, mode)]
            host = str(kwargs.get("host") or vars_.get("inventory_hostname", ""))
            bin_dir = kwargs.get("bin_dir")
            if not bin_dir:
                raise AnsibleError(
                    "db_backup: 'local' needs bin_dir, the directory of the primary probes"
                )
            return [local_backup_instances(groups, mode, host, str(bin_dir))]
        except DbInstancesError as exc:
            raise AnsibleError(str(exc)) from exc
