"""L06: every identity account of lookup('users') matches [a-z1-9]{3,15} (a
reserved account with no identity account is exempt); every agent account is
``<role code>0<suffix>`` within IAM_ACCOUNT_MAX_LENGTH, and instance ids match
[a-z1-9]{1,15}. The account-name generator takes its ceilings from the account
policy every role declares, so the lint and the deploy agree on one bound."""

from __future__ import annotations

import unittest

from tests.lint.agents import AGENTS_DIR, PROJECT_ROOT, load
from tests.lint.ansible.roles.meta.test_identity_username_charset import (
    offenders,
    username_max_length,
)
from utils.agents import naming
from utils.cache.users import get_user_defaults
from utils.roles import account_policy

INSTANCE_IDS_OK = ("a", "dev1", "laptop", "abcdefghijklmno")
INSTANCE_IDS_BAD = ("", "dev-laptop", "dev0", "Laptop", "abcdefghijklmnop")


def ceiling_problems(policies: dict) -> list[str]:
    """Return every ceiling of the name generator that differs from the policy.

    Args:
        policies: ``{role: account_policy}`` from ``account_policy.load_policies``.
    """
    problems: list[str] = []
    agent = account_policy.account_max_length(policies)
    human = account_policy.username_max_length(policies)
    if agent != naming.IAM_ACCOUNT_MAX_LENGTH:
        problems.append(
            f"naming.IAM_ACCOUNT_MAX_LENGTH {naming.IAM_ACCOUNT_MAX_LENGTH} != {agent}"
        )
    if human != naming.IAM_USERNAME_MAX_LENGTH:
        problems.append(
            f"naming.IAM_USERNAME_MAX_LENGTH {naming.IAM_USERNAME_MAX_LENGTH} != {human}"
        )
    return problems


def code_problems(codes: dict) -> list[str]:
    """Return every role code whose longest agent name breaks the agent form.

    Args:
        codes: the agents/codes.yml mapping of role to code.
    """
    problems: list[str] = []
    longest = naming.IAM_ACCOUNT_MAX_LENGTH - 5
    for role, code in sorted(codes.items()):
        try:
            name = naming.agent_account_name(str(code), "a" * longest)
        except ValueError as error:
            problems.append(f"{role}: {error}")
            continue
        if not naming.is_agent_name(name):
            problems.append(f"{role}: {name!r} is not an agent account name")
    return problems


def instance_id_problems(
    accepted: tuple[str, ...], refused: tuple[str, ...]
) -> list[str]:
    """Return every instance id the generator judges against the rule.

    Args:
        accepted: ids of ``[a-z1-9]{1,15}`` that must yield an account.
        refused: ids outside the rule that must be refused.
    """
    problems = [
        f"instance id {value!r} refused"
        for value in accepted
        if not naming.is_instance_id(value)
    ]
    problems.extend(
        f"instance id {value!r} accepted"
        for value in refused
        if naming.is_instance_id(value)
    )
    return problems


class TestL06(unittest.TestCase):
    def test_identity_accounts_match_the_human_rule(self):
        users = get_user_defaults(roles_dir=str(PROJECT_ROOT / "roles"))
        self.assertEqual(offenders(users, username_max_length()), [])

    def test_the_generator_ceilings_equal_the_account_policy(self):
        policies = account_policy.load_policies(PROJECT_ROOT / "roles")
        self.assertEqual(ceiling_problems(policies), [])

    def test_every_role_code_fits_the_longest_agent_name(self):
        self.assertEqual(code_problems(load(AGENTS_DIR / "codes.yml")), [])

    def test_instance_ids_follow_the_rule(self):
        self.assertEqual(instance_id_problems(INSTANCE_IDS_OK, INSTANCE_IDS_BAD), [])

    def test_a_trailing_newline_is_refused_by_every_check(self):
        for check, value in (
            (naming.is_agent_name, "mant0alice\n"),
            (naming.is_human_name, "alice\n"),
            (naming.is_instance_id, "dev1\n"),
        ):
            with self.subTest(check=check.__name__):
                self.assertFalse(check(value))
        for code, suffix in (("mant\n", "alice"), ("mant", "alice\n")):
            with self.subTest(code=code, suffix=suffix), self.assertRaises(ValueError):
                naming.agent_account_name(code, suffix)

    def test_red_fixture_fails(self):
        self.assertNotEqual(code_problems({"ghost": "gh0s"}), [])
        self.assertNotEqual(instance_id_problems(("dev-laptop",), ("dev1",)), [])
        self.assertNotEqual(
            offenders({"x": {"accounts": ["identity"], "username": "bot0x"}}, 15), []
        )
        shrunk = {"r": {"username_max_length": 12, "agent_reachable": True}}
        self.assertNotEqual(ceiling_problems(shrunk), [])


if __name__ == "__main__":
    unittest.main()
