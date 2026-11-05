"""Lookup `patroni_config`: Patroni configuration of the Postgres HA form.

    lookup('patroni_config', 'file', scope=..., etcd_hosts=..., ...)
    lookup('patroni_config', 'dynamic', parameters=..., replication_subnet=...,
           replication_user=..., rewind_user=...)

``file`` returns the shared ``patroni.yml`` text, ``dynamic`` the cluster-wide
configuration dict Ansible re-applies on every run. Arguments are those of
``utils.roles.patroni_config.render_patroni_yml`` / ``dynamic_config``.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase

from utils.roles.patroni_config import (
    PatroniConfigError,
    dynamic_config,
    render_patroni_yml,
)
from utils.templating.ansible import to_plain


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        terms = terms or []
        kwargs = to_plain(kwargs)
        if len(terms) != 1 or terms[0] not in ("file", "dynamic"):
            raise AnsibleError("patroni_config: expected one term, 'file' or 'dynamic'")
        try:
            if terms[0] == "dynamic":
                return [
                    dynamic_config(
                        kwargs["parameters"],
                        str(kwargs["replication_subnet"]),
                        str(kwargs["replication_user"]),
                        str(kwargs["rewind_user"]),
                    )
                ]
            return [render_patroni_yml(**kwargs)]
        except (PatroniConfigError, KeyError, TypeError) as exc:
            raise AnsibleError(f"patroni_config: {exc}") from exc
