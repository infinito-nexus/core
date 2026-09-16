"""Lookup `role_subnets`: the local subnets other roles declare.

Single SPOT for "which address block does role X own". The block is declared
once, in that role's ``meta/networks.yml``; anything that has to reason about
the deployment's own address space reads it from here instead of repeating the
literal, which is how a CIDR ends up stated twice and then drifts.

Usage:

    {{ lookup('role_subnets', 'web-app-bigbluebutton') }}   # ['10.7.7.0/24']
    {{ lookup('role_subnets', SOME_ROLE_LIST) }}            # one entry per role

Terms may be role ids or lists of them, mixed. A role that declares no local
subnet raises, because a silently dropped entry would narrow whatever firewall
or trust list consumes the result.
"""

from __future__ import annotations

from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.loader import lookup_loader
from ansible.plugins.lookup import LookupBase

_SUBNET_PATH = "networks.local.subnet"


def _flattened(terms: list[Any]) -> list[str]:
    roles: list[str] = []
    for term in terms:
        if isinstance(term, (list, tuple)):
            roles.extend(str(entry).strip() for entry in term)
        else:
            roles.append(str(term).strip())
    return [role for role in roles if role]


class LookupModule(LookupBase):
    def run(
        self,
        terms: list[Any] | None,
        variables: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[Any]:
        roles = _flattened(terms or [])
        if not roles:
            raise AnsibleError(
                "lookup('role_subnets', <role id or list of role ids>) expects "
                "at least one role id"
            )
        config = lookup_loader.get(
            "config",
            loader=getattr(self, "_loader", None),
            templar=getattr(self, "_templar", None),
        )
        subnets: list[str] = []
        for role in roles:
            value = config.run([role, _SUBNET_PATH], variables=variables)[0]
            text = "" if value is None else str(value).strip()
            if not text:
                raise AnsibleError(f"role_subnets: '{role}' declares no {_SUBNET_PATH}")
            subnets.append(text)
        return [subnets]
