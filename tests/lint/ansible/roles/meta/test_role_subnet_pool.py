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

A role that genuinely cannot choose its block declares that next to the block,
with ``local.outside_pool: true`` in its ``meta/networks.yml``.
``NETWORK_ROLE_SUBNET_EXCEPTION_ROLES`` collects those roles through
``lookup('role_subnet_exceptions')`` rather than listing them, so the
declaration is never stated twice, and consumers resolve the ids through
``lookup('role_subnets', ...)``.
"""

from __future__ import annotations

import ipaddress
import unittest

import jinja2

from utils.cache.yaml import load_yaml_any
from utils.meta.scan import iter_outside_pool_roles, iter_subnets

from . import PROJECT_ROOT

NETWORKS_FILE = PROJECT_ROOT / "group_vars" / "all" / "08_networks.yml"


def _declared_space() -> tuple[list[ipaddress.IPv4Network], list[str]]:
    """The pool plus the blocks of the excepted roles, with their raw strings."""
    data = load_yaml_any(str(NETWORKS_FILE), default_if_missing={}) or {}
    pool = data.get("NETWORK_ROLE_SUBNET_POOL")
    if isinstance(pool, str) and "{{" in pool:
        pool = jinja2.Template(
            pool, autoescape=jinja2.select_autoescape(default_for_string=False)
        ).render(**data)
    if not isinstance(pool, str):
        raise TypeError(
            f"{NETWORKS_FILE} must declare NETWORK_ROLE_SUBNET_POOL as a string"
        )
    declared = dict(iter_subnets())
    raw = [pool]
    for role in iter_outside_pool_roles():
        subnet = declared.get(role)
        if subnet is None:
            raise AssertionError(
                f"{role} sets networks.local.outside_pool but declares no "
                "networks.local.subnet"
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
                "block is pinned by something outside this repository, set "
                "networks.local.outside_pool: true in the role's "
                "meta/networks.yml."
            )

    def test_the_exceptions_are_collected_from_the_roles(self) -> None:
        data = load_yaml_any(str(NETWORKS_FILE), default_if_missing={}) or {}
        self.assertEqual(
            data.get("NETWORK_ROLE_SUBNET_EXCEPTION_ROLES"),
            "{{ lookup('role_subnet_exceptions') }}",
            f"{NETWORKS_FILE}: NETWORK_ROLE_SUBNET_EXCEPTION_ROLES must collect "
            "the roles that set networks.local.outside_pool, not list them",
        )

    def test_the_exceptions_are_not_already_covered(self) -> None:
        """An exception inside the pool is dead weight that outlives its reason."""
        allowed, raw = _declared_space()
        pool = allowed[0]
        redundant = [entry for entry in allowed[1:] if entry.subnet_of(pool)]
        if redundant:
            self.fail(
                "networks.local.outside_pool is set on role(s) whose subnet "
                f"already sits inside {raw[0]}: "
                f"{', '.join(str(entry) for entry in redundant)}. "
                "Drop the flag; the pool already admits those addresses."
            )


if __name__ == "__main__":
    unittest.main()
