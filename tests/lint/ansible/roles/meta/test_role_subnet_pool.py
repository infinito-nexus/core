"""Lint: a role's local subnet comes out of the declared pool.

``NETWORK_ROLE_SUBNET_POOL`` in ``group_vars/all/08_networks.yml`` names the
block role networks are carved from. Until it existed the block was an emergent
property: the allocator in ``cli contributing network address suggest`` derives
its umbrella from the subnets already in use, so the tree defined the rule
instead of the rule defining the tree. Anything that consumes "our own address
space" then has to guess, and a guess that is one role out of date silently
excludes that role. That is not hypothetical: a firewall range derived from the
pool by eye would have cut BigBlueButton off, because its subnet is the one
that sits outside.

A role that genuinely cannot choose its block is named in
``NETWORK_ROLE_SUBNET_EXCEPTION_ROLES``. The list carries role ids rather than
CIDRs on purpose: the block is already declared in that role's
``meta/networks.yml``, and repeating it here would be the same duplication one
layer up. Consumers resolve the ids through ``lookup('role_subnets', ...)``.
"""

from __future__ import annotations

import ipaddress
import unittest

import jinja2

from utils.cache.yaml import load_yaml_any
from utils.meta.scan import iter_subnets

from . import PROJECT_ROOT

NETWORKS_FILE = PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"


def _declared_space() -> tuple[list[ipaddress.IPv4Network], list[str]]:
    """The pool plus the blocks of the excepted roles, with their raw strings."""
    data = load_yaml_any(str(NETWORKS_FILE), default_if_missing={}) or {}
    pool = data.get("NETWORK_ROLE_SUBNET_POOL")
    if isinstance(pool, str) and "{{" in pool:
        pool = jinja2.Template(pool).render(**data)
    roles = data.get("NETWORK_ROLE_SUBNET_EXCEPTION_ROLES") or []
    if not isinstance(pool, str) or not isinstance(roles, list):
        raise TypeError(
            f"{NETWORKS_FILE} must declare NETWORK_ROLE_SUBNET_POOL as a string "
            "and NETWORK_ROLE_SUBNET_EXCEPTION_ROLES as a list of role ids"
        )
    declared = dict(iter_subnets())
    raw = [pool]
    for role in roles:
        subnet = declared.get(str(role))
        if subnet is None:
            raise AssertionError(
                f"{NETWORKS_FILE}: NETWORK_ROLE_SUBNET_EXCEPTION_ROLES names "
                f"'{role}', which declares no networks.local.subnet"
            )
        raw.append(str(subnet))
    return [ipaddress.ip_network(entry, strict=True) for entry in raw], raw


class TestRoleSubnetPool(unittest.TestCase):
    def test_every_role_subnet_sits_in_the_declared_space(self) -> None:
        allowed, raw = _declared_space()
        findings = [
            f"- {role}: {subnet}"
            for role, subnet in sorted(iter_subnets(), key=lambda item: item[0])
            if not any(subnet.subnet_of(block) for block in allowed)
        ]
        if findings:
            self.fail(
                "These roles declare networks.local.subnet outside the address "
                "space this deployment declares for itself:\n"
                + "\n".join(findings)
                + "\n\nDeclared space: "
                + ", ".join(raw)
                + "\n\nFix: pick a subnet inside the pool via "
                "`infinito contributing network address suggest`, or, when the "
                "block is pinned by something outside this repository, name the "
                "role in NETWORK_ROLE_SUBNET_EXCEPTION_ROLES in "
                "group_vars/all/08_networks.yml."
            )

    def test_the_exceptions_are_not_already_covered(self) -> None:
        """An exception inside the pool is dead weight that outlives its reason."""
        allowed, raw = _declared_space()
        pool = allowed[0]
        redundant = [entry for entry in allowed[1:] if entry.subnet_of(pool)]
        if redundant:
            self.fail(
                "NETWORK_ROLE_SUBNET_EXCEPTION_ROLES names role(s) whose subnet "
                f"already sits inside {raw[0]}: "
                f"{', '.join(str(entry) for entry in redundant)}. "
                "Remove them; the pool already admits those addresses."
            )


if __name__ == "__main__":
    unittest.main()
